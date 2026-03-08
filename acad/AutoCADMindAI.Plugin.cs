using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.Windows;
using System.Windows.Forms;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Application;


[assembly: ExtensionApplication(typeof(AutoCADMindAIPlugin.PluginEntry))]
[assembly: CommandClass(typeof(AutoCADMindAIPlugin.PluginEntry))]

namespace AutoCADMindAIPlugin
{
    public class PluginEntry : IExtensionApplication
    {
        private const string BridgeBaseUrl = "http://127.0.0.1:8765";

        private static readonly HttpClient Http = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(2)
        };

        private static PaletteSet _aiPalette;
        private static AIPaletteControl _aiPaletteControl;

        public void Initialize()
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument;
            var ed = doc?.Editor;
            if (ed != null)
            {
                ed.WriteMessage("\n[AutoCADMindAI] 插件初始化成功。推荐命令: AIMIND（开发调试: AICHAT, AISTOP, AISTART, AIPING）");
            }
            Write("AutoCADMindAI 插件已加载。默认入口: AIMIND。开发调试命令: AICHAT, AISTOP, AISTART, AIPING");
        }

        public void Terminate()
        {
            try
            {
                if (_aiPalette != null)
                {
                    _aiPalette.Visible = false;
                }
            }
            catch { }
        }

        [CommandMethod("AIMIND", CommandFlags.Modal)]
        public void AIMIND()
        {
            var ed = AcApp.DocumentManager.MdiActiveDocument?.Editor;
            ed?.WriteMessage("\n[AutoCADMindAI] AIMIND 已触发");
            AppendStartupLog("C#", "AIMIND command triggered.");

            if (EnsureBridgeReady(ed))
            {
                EnsurePalette();
                _aiPalette.Visible = true;
                _aiPalette.KeepFocus = true;
                _aiPaletteControl?.SetStatus("就绪");
                Write("AI 面板已就绪，你可以直接输入需求。", ed);
                AppendStartupLog("C#", "AIMIND flow ready: bridge alive and palette shown.");
            }
        }

        [CommandMethod("AISTART", CommandFlags.Modal)]
        public void AISTART()
        {
            var ed = AcApp.DocumentManager.MdiActiveDocument?.Editor;
            Write("AISTART 为开发者调试命令。普通用户请直接使用 AIMIND。", ed);

            if (EnsureBridgeReady(ed))
            {
                Write("Bridge 启动完成（开发者模式）。", ed);
            }
        }

        [CommandMethod("AIPING", CommandFlags.Modal)]
        public void AIPING()
        {
            var ed = AcApp.DocumentManager.MdiActiveDocument?.Editor;
            Write("AIPING 为开发者调试命令。普通用户请直接使用 AIMIND。", ed);

            if (IsBridgeAlive())
                Write("Bridge 正常: " + BridgeBaseUrl, ed);
            else
                Write("Bridge 不可用: " + BridgeBaseUrl + "（请确认地址是 127.0.0.1）。", ed);
        }

        [CommandMethod("AICHAT", CommandFlags.Modal)]
        public void AICHAT()
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument;
            if (doc == null) return;
            if (!EnsureBridgeReady(doc.Editor))
            {
                return;
            }
            PostJson("/show", "{}");

            var input = doc.Editor.GetString("\n输入给 AI 的内容: ");
            if (input.Status != PromptStatus.OK || string.IsNullOrWhiteSpace(input.StringResult))
                return;

            PostJson("/chat", "{\"text\":\"" + EscapeJson(input.StringResult) + "\"}");
            Write("已发送到 AI。", doc.Editor);
        }

        [CommandMethod("AISTOP", CommandFlags.Modal)]
        public void AISTOP()
        {
            PostJson("/stop", "{}");
            Write("已请求停止。", AcApp.DocumentManager.MdiActiveDocument?.Editor);
        }

        [CommandMethod("AICANCEL", CommandFlags.Modal)]
        public void AICANCEL()
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument;
            var ed = doc?.Editor;
            if (doc != null)
            {
                try
                {
                    doc.SendStringToExecute("\x03\x03 ", true, false, false);
                }
                catch { }
            }
            Write("已向AutoCAD发送取消（Ctrl+C, Ctrl+C）。", ed);
        }


        private static bool IsBridgeAlive()
        {
            try
            {
                var resp = Http.GetAsync(BridgeBaseUrl + "/health").GetAwaiter().GetResult();
                return resp.IsSuccessStatusCode;
            }
            catch
            {
                return false;
            }
        }

        private static bool EnsureBridgeReady(Editor ed)
        {
            if (IsBridgeAlive())
            {
                AppendStartupLog("C#", "Bridge health check passed directly.");
                return true;
            }

            Write("正在启动 AI 服务，请稍候...", ed);
            AppendStartupLog("C#", "Bridge health check failed, start bootstrap now.");
            if (!StartPythonUi())
            {
                AppendStartupLog("C#", "Bootstrap failed: unable to launch start script.");
                Write("启动失败：未能执行启动脚本。建议：1) 检查发布目录里是否有 start.bat/start.py；2) 检查 Python 是否安装可用。", ed);
                return false;
            }

            // 冷启动等待：总计约 30 秒（依赖检查/首次加载可能较慢）
            for (int i = 0; i < 150; i++)
            {
                if (IsBridgeAlive())
                {
                    AppendStartupLog("C#", "Bridge became healthy after bootstrap.");
                    return true;
                }
                System.Threading.Thread.Sleep(200);
            }

            var pluginDir = Path.GetDirectoryName(typeof(PluginEntry).Assembly.Location) ?? Environment.CurrentDirectory;
            var logPath = Path.Combine(pluginDir, "bridge_start.log");
            AppendStartupLog("C#", "Bridge still not ready after wait timeout.");
            Write("AI 服务还没准备好。建议：1) 打开日志 " + logPath + " 查看最后几行；2) 检查 8765 端口是否被占用；3) 双击 start.bat 看是否有缺失依赖。", ed);
            return false;
        }

        private static bool StartPythonUi()
        {
            var ed = AcApp.DocumentManager.MdiActiveDocument?.Editor;
            var pluginDir = Path.GetDirectoryName(typeof(PluginEntry).Assembly.Location) ?? Environment.CurrentDirectory;

            if (IsBridgeAlive()) return true;

            // 1) 优先直接拉起 main_ai_cad.py，避免 start.bat/start.py 的编码与阻塞差异
            var mainPy = Path.Combine(pluginDir, "main_ai_cad.py");
            if (File.Exists(mainPy))
            {
                try
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = "py",
                        Arguments = "\"" + mainPy + "\"",
                        WorkingDirectory = pluginDir,
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        WindowStyle = ProcessWindowStyle.Hidden
                    });
                    Write("已后台通过 py 启动 main_ai_cad.py。", ed);
                    AppendStartupLog("C#", "Background launch main_ai_cad.py via py success.");
                    return true;
                }
                catch (System.Exception ex)
                {
                    AppendStartupLog("C#", "Launch main_ai_cad.py via py failed: " + ex.Message);
                }

                try
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = "python",
                        Arguments = "\"" + mainPy + "\"",
                        WorkingDirectory = pluginDir,
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        WindowStyle = ProcessWindowStyle.Hidden
                    });
                    Write("已后台通过 python 启动 main_ai_cad.py。", ed);
                    AppendStartupLog("C#", "Background launch main_ai_cad.py via python success.");
                    return true;
                }
                catch (System.Exception ex)
                {
                    AppendStartupLog("C#", "Launch main_ai_cad.py via python failed: " + ex.Message);
                }
            }

            // 2) 回退 bat（保持兼容）
            var startBat = Path.Combine(pluginDir, "start.bat");
            if (File.Exists(startBat))
            {
                try
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = startBat,
                        WorkingDirectory = pluginDir,
                        UseShellExecute = true,
                        CreateNoWindow = true,
                        WindowStyle = ProcessWindowStyle.Hidden
                    });
                    Write("已后台启动 start.bat。", ed);
                    AppendStartupLog("C#", "Background launch start.bat success.");
                    return true;
                }
                catch (System.Exception ex)
                {
                    AppendStartupLog("C#", "Background launch start.bat failed: " + ex.Message);
                }
            }

            AppendStartupLog("C#", "Missing launch target: main_ai_cad.py/start.bat not found.");
            Write("未找到可启动文件（main_ai_cad.py 或 start.bat）。请检查发布目录是否完整。", ed);
            return false;
        }

        private static void EnsurePalette()
        {
            if (_aiPalette != null && _aiPaletteControl != null) return;

            _aiPalette = new PaletteSet("AutoCADMindAI")
            {
                Style = PaletteSetStyles.NameEditable |
                        PaletteSetStyles.ShowAutoHideButton |
                        PaletteSetStyles.ShowCloseButton |
                        PaletteSetStyles.Snappable,
                DockEnabled = DockSides.Left | DockSides.Right,
                MinimumSize = new System.Drawing.Size(300, 220),
                Size = new System.Drawing.Size(360, 300)
            };

            _aiPaletteControl = new AIPaletteControl();
            _aiPaletteControl.SendRequested += OnPaletteSendRequested;
            _aiPaletteControl.StopRequested += OnPaletteStopRequested;
            _aiPalette.Add("AI", _aiPaletteControl);
        }

        private static void OnPaletteSendRequested(string text)
        {
            var ed = AcApp.DocumentManager.MdiActiveDocument?.Editor;
            if (!EnsureBridgeReady(ed))
            {
                _aiPaletteControl?.SetStatus("未连接");
                return;
            }

            var payload = "{\"text\":\"" + EscapeJson(text) + "\"}";
            var ok = PostJsonWithResult("/chat", payload);
            _aiPaletteControl?.SetStatus(ok ? "已发送" : "发送失败");
            if (!ok)
            {
                Write("发送失败，请检查 bridge_start.log。", ed);
            }
        }

        private static void OnPaletteStopRequested()
        {
            var ok = PostJsonWithResult("/stop", "{}");
            _aiPaletteControl?.SetStatus(ok ? "已停止" : "停止失败");
        }

        private static bool PostJsonWithResult(string path, string json)
        {
            try
            {
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                var resp = Http.PostAsync(BridgeBaseUrl + path, content).GetAwaiter().GetResult();
                return resp.IsSuccessStatusCode;
            }
            catch
            {
                return false;
            }
        }

        private static void PostJson(string path, string json)
        {
            try
            {
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                var resp = Http.PostAsync(BridgeBaseUrl + path, content).GetAwaiter().GetResult();
                // 这里不抛异常，避免打断 AutoCAD 命令流
            }
            catch
            {
                // ignored
            }
        }

        private static void AppendStartupLog(string source, string message)
        {
            try
            {
                var pluginDir = Path.GetDirectoryName(typeof(PluginEntry).Assembly.Location) ?? Environment.CurrentDirectory;
                var logFile = Path.Combine(pluginDir, "bridge_start.log");
                var line = "[" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff") + "] [" + source + "] " + message + Environment.NewLine;
                File.AppendAllText(logFile, line, Encoding.UTF8);
            }
            catch
            {
                // 避免日志写入问题影响主流程
            }
        }

        private static void Write(string message, Editor ed = null)
        {
            var editor = ed ?? AcApp.DocumentManager.MdiActiveDocument?.Editor;
            editor?.WriteMessage("\n[AutoCADMindAI] " + message);
        }

        private static string EscapeJson(string s)
        {
            if (string.IsNullOrEmpty(s)) return string.Empty;
            return s
                .Replace("\\", "\\\\")
                .Replace("\"", "\\\"")
                .Replace("\r", "\\r")
                .Replace("\n", "\\n");
        }
    }

    internal sealed class AIPaletteControl : UserControl
    {
        private readonly TextBox _input;
        private readonly Button _sendButton;
        private readonly Button _stopButton;
        private readonly Label _statusLabel;

        public event Action<string> SendRequested;
        public event Action StopRequested;

        public AIPaletteControl()
        {
            Dock = DockStyle.Fill;

            var panel = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                ColumnCount = 2,
                RowCount = 3,
                Padding = new Padding(8)
            };
            panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            panel.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 90));
            panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            panel.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            var title = new Label
            {
                Text = "AutoCADMindAI",
                Dock = DockStyle.Fill,
                AutoSize = true
            };
            panel.Controls.Add(title, 0, 0);
            panel.SetColumnSpan(title, 2);

            _input = new TextBox
            {
                Multiline = true,
                Dock = DockStyle.Fill,
                ScrollBars = ScrollBars.Vertical
            };
            panel.Controls.Add(_input, 0, 1);
            panel.SetColumnSpan(_input, 2);

            _sendButton = new Button
            {
                Text = "发送",
                Dock = DockStyle.Fill
            };
            _sendButton.Click += (_, __) =>
            {
                var text = (_input.Text ?? string.Empty).Trim();
                if (string.IsNullOrWhiteSpace(text))
                {
                    SetStatus("请输入内容");
                    return;
                }
                SendRequested?.Invoke(text);
            };

            _stopButton = new Button
            {
                Text = "停止",
                Dock = DockStyle.Fill
            };
            _stopButton.Click += (_, __) => StopRequested?.Invoke();

            var btnPanel = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                ColumnCount = 2,
                RowCount = 1
            };
            btnPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            btnPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            btnPanel.Controls.Add(_sendButton, 0, 0);
            btnPanel.Controls.Add(_stopButton, 1, 0);

            panel.Controls.Add(btnPanel, 0, 2);

            _statusLabel = new Label
            {
                Text = "状态：未连接",
                Dock = DockStyle.Fill,
                TextAlign = System.Drawing.ContentAlignment.MiddleRight
            };
            panel.Controls.Add(_statusLabel, 1, 2);

            Controls.Add(panel);
        }

        public void SetStatus(string status)
        {
            _statusLabel.Text = "状态：" + status;
        }
    }
}
