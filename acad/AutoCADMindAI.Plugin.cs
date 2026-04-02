using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Text.Json;
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
        private static int _lastAiSeq;

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

            // 先显示面板
            EnsurePalette();
            _aiPalette.Visible = true;
            _aiPalette.KeepFocus = true;
            _aiPaletteControl?.SetStatus("正在启动服务...");
            Write("正在后台启动 AI 服务...", ed);

            // 异步启动 bridge，不阻塞主线程
            System.Threading.Tasks.Task.Run(() =>
            {
                var bridgeOk = EnsureBridgeReady(ed);
                
                // 回到 UI 线程更新状态
                if (_aiPaletteControl != null)
                {
                    if (_aiPaletteControl.InvokeRequired)
                    {
                        _aiPaletteControl.Invoke(new Action(() =>
                        {
                            _aiPaletteControl.SetStatus(bridgeOk ? "就绪" : "启动失败");
                            if (bridgeOk)
                            {
                                _aiPaletteControl.AppendSystemMessage("AI 服务已就绪，你可以直接输入需求。", false);
                            }
                            else
                            {
                                _aiPaletteControl.AppendSystemMessage("AI 服务启动失败，请查看日志。", true);
                            }
                        }));
                    }
                }
                
                if (bridgeOk)
                {
                    _lastAiSeq = 0;
                }
            });
            
            AppendStartupLog("C#", "AIMIND flow: palette shown, bridge starting async.");
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

            // 尝试多个可能的路径
            var searchPaths = new[]
            {
                pluginDir,
                Path.GetFullPath(Path.Combine(pluginDir, "..")),
                Path.GetFullPath(Path.Combine(pluginDir, "..", "..")),
                @"e:\user\桌面\AutoCADMindAI",
                @"e:\user\桌面\AutoCADMindAI\dist\AutoCADMindAI",
            };

            foreach (var searchDir in searchPaths)
            {
                if (string.IsNullOrEmpty(searchDir) || !Directory.Exists(searchDir))
                    continue;

                AppendStartupLog("C#", "Checking path: " + searchDir);

                // 优先使用 start.bat
                var startBat = Path.Combine(searchDir, "start.bat");
                if (File.Exists(startBat))
                {
                    try
                    {
                        Process.Start(new ProcessStartInfo
                        {
                            FileName = startBat,
                            WorkingDirectory = searchDir,
                            UseShellExecute = true,
                            CreateNoWindow = true,
                            WindowStyle = ProcessWindowStyle.Hidden
                        });
                        Write("已后台启动 start.bat。", ed);
                        AppendStartupLog("C#", "Background launch start.bat success from: " + searchDir);
                        return true;
                    }
                    catch (System.Exception ex)
                    {
                        AppendStartupLog("C#", "Background launch start.bat failed: " + ex.Message);
                    }
                }

                // 回退：直接拉起 main_ai_cad.py
                var mainPy = Path.Combine(searchDir, "main_ai_cad.py");
                if (File.Exists(mainPy))
                {
                    // 尝试 py
                    try
                    {
                        Process.Start(new ProcessStartInfo
                        {
                            FileName = "py",
                            Arguments = "\"" + mainPy + "\"",
                            WorkingDirectory = searchDir,
                            UseShellExecute = false,
                            CreateNoWindow = true,
                            WindowStyle = ProcessWindowStyle.Hidden
                        });
                        Write("已后台通过 py 启动 main_ai_cad.py。", ed);
                        AppendStartupLog("C#", "Background launch main_ai_cad.py via py success from: " + searchDir);
                        return true;
                    }
                    catch (System.Exception ex)
                    {
                        AppendStartupLog("C#", "Launch main_ai_cad.py via py failed: " + ex.Message);
                    }

                    // 尝试 python
                    try
                    {
                        Process.Start(new ProcessStartInfo
                        {
                            FileName = "python",
                            Arguments = "\"" + mainPy + "\"",
                            WorkingDirectory = searchDir,
                            UseShellExecute = false,
                            CreateNoWindow = true,
                            WindowStyle = ProcessWindowStyle.Hidden
                        });
                        Write("已后台通过 python 启动 main_ai_cad.py。", ed);
                        AppendStartupLog("C#", "Background launch main_ai_cad.py via python success from: " + searchDir);
                        return true;
                    }
                    catch (System.Exception ex)
                    {
                        AppendStartupLog("C#", "Launch main_ai_cad.py via python failed: " + ex.Message);
                    }
                }
            }

            AppendStartupLog("C#", "Missing launch target: main_ai_cad.py/start.bat not found in any search path.");
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
                MinimumSize = new System.Drawing.Size(360, 360),
                Size = new System.Drawing.Size(420, 520)
            };

            _aiPaletteControl = new AIPaletteControl();
            _aiPaletteControl.SendRequested += OnPaletteSendRequested;
            _aiPaletteControl.StopRequested += OnPaletteStopRequested;
            _aiPaletteControl.StartRequested += OnPaletteStartRequested;
            _aiPaletteControl.PingRequested += OnPalettePingRequested;
            _aiPaletteControl.CancelRequested += OnPaletteCancelRequested;
            _aiPaletteControl.ClearRequested += OnPaletteClearRequested;
            _aiPalette.Add("AI", _aiPaletteControl);
        }

        private static void OnPaletteSendRequested(string text)
        {
            var ed = AcApp.DocumentManager.MdiActiveDocument?.Editor;
            _aiPaletteControl?.SetBusy(true);
            _aiPaletteControl?.AppendUserMessage(text);
            _aiPaletteControl?.ClearInput();

            if (!EnsureBridgeReady(ed))
            {
                _aiPaletteControl?.SetStatus("未连接");
                _aiPaletteControl?.AppendSystemMessage("AI 服务未连接，请先点击\"启动服务\"或检查 bridge_start.log。", true);
                _aiPaletteControl?.SetBusy(false);
                return;
            }

            var payload = "{\"text\":\"" + EscapeJson(text) + "\"}";
            var body = PostJsonGetBody("/chat", payload);
            var ackMessage = TryExtractBridgeMessage(body);
            var ok = !string.IsNullOrWhiteSpace(body);

            _aiPaletteControl?.SetStatus(ok ? "已发送" : "发送失败");
            if (ok)
            {
                _aiPaletteControl?.AppendSystemMessage(string.IsNullOrWhiteSpace(ackMessage) ? "请求已提交到 AI，处理中..." : ackMessage, false);

                var aiMessage = PollLatestAiMessage();
                if (!string.IsNullOrWhiteSpace(aiMessage))
                {
                    _aiPaletteControl?.AppendAssistantMessage(aiMessage);
                    _aiPaletteControl?.SetStatus("已回复");
                }
                else
                {
                    _aiPaletteControl?.AppendSystemMessage("AI 仍在处理中，请稍候再发一条或点击检测连接。", false);
                }
            }
            else
            {
                _aiPaletteControl?.AppendSystemMessage("请求发送失败，请检查 bridge_start.log。", true);
            }
            _aiPaletteControl?.SetBusy(false);

            if (!ok)
            {
                Write("发送失败，请检查 bridge_start.log。", ed);
            }
        }

        private static void OnPaletteStopRequested()
        {
            var ok = PostJsonWithResult("/stop", "{}");
            _aiPaletteControl?.SetStatus(ok ? "已停止" : "停止失败");
            _aiPaletteControl?.AppendSystemMessage(ok ? "已发送停止请求。" : "停止请求失败。", !ok);
        }

        private static void OnPaletteStartRequested()
        {
            var ed = AcApp.DocumentManager.MdiActiveDocument?.Editor;
            var ok = EnsureBridgeReady(ed);
            _aiPaletteControl?.SetStatus(ok ? "就绪" : "未连接");
            _aiPaletteControl?.AppendSystemMessage(ok ? "AI 服务已就绪。" : "AI 服务启动失败，请查看日志。", !ok);
        }

        private static void OnPalettePingRequested()
        {
            var ok = IsBridgeAlive();
            _aiPaletteControl?.SetStatus(ok ? "在线" : "离线");
            _aiPaletteControl?.AppendSystemMessage(ok ? "Bridge 心跳正常。" : "Bridge 心跳失败。", !ok);
        }

        private static void OnPaletteCancelRequested()
        {
            var doc = AcApp.DocumentManager.MdiActiveDocument;
            var ed = doc?.Editor;
            if (doc != null)
            {
                try
                {
                    doc.SendStringToExecute("\x03\x03 ", true, false, false);
                    _aiPaletteControl?.AppendSystemMessage("已发送 AutoCAD 取消命令（Ctrl+C x2）。", false);
                    _aiPaletteControl?.SetStatus("已取消当前命令");
                }
                catch
                {
                    _aiPaletteControl?.AppendSystemMessage("取消命令发送失败。", true);
                    _aiPaletteControl?.SetStatus("取消失败");
                }
            }
            else
            {
                _aiPaletteControl?.AppendSystemMessage("当前无活动文档，无法取消命令。", true);
                _aiPaletteControl?.SetStatus("无活动文档");
            }

            Write("已向AutoCAD发送取消（Ctrl+C, Ctrl+C）。", ed);
        }

        private static void OnPaletteClearRequested()
        {
            _aiPaletteControl?.ClearConversation();
            _aiPaletteControl?.SetStatus("已清空会话");
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

        private static string PostJsonGetBody(string path, string json)
        {
            try
            {
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                var resp = Http.PostAsync(BridgeBaseUrl + path, content).GetAwaiter().GetResult();
                if (!resp.IsSuccessStatusCode) return null;
                return resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            }
            catch
            {
                return null;
            }
        }

        private static string TryExtractBridgeMessage(string jsonBody)
        {
            if (string.IsNullOrWhiteSpace(jsonBody)) return null;
            try
            {
                using var doc = JsonDocument.Parse(jsonBody);
                if (!doc.RootElement.TryGetProperty("message", out var msgElement)) return null;
                var msg = msgElement.GetString();
                return string.IsNullOrWhiteSpace(msg) ? null : msg;
            }
            catch
            {
                return null;
            }
        }

        private static string PollLatestAiMessage()
        {
            // 增加超时时间到 60 秒，适应 AI 模型加载和复杂绘图
            for (int i = 0; i < 300; i++)
            {
                try
                {
                    var resp = Http.GetAsync(BridgeBaseUrl + "/last_ai?since=" + _lastAiSeq).GetAwaiter().GetResult();
                    if (resp.IsSuccessStatusCode)
                    {
                        var body = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                        using var doc = JsonDocument.Parse(body);

                        var hasNew = doc.RootElement.TryGetProperty("has_new", out var hasNewElement) && hasNewElement.GetBoolean();
                        var remoteSeq = _lastAiSeq;
                        if (doc.RootElement.TryGetProperty("seq", out var seqElement) && seqElement.ValueKind == JsonValueKind.Number)
                        {
                            remoteSeq = seqElement.GetInt32();
                        }

                        // Python 端重启后 seq 可能回到 0，避免卡在旧序号导致永远拿不到新消息
                        if (remoteSeq < _lastAiSeq)
                        {
                            _lastAiSeq = 0;
                        }
                        else
                        {
                            _lastAiSeq = remoteSeq;
                        }

                        if (hasNew)
                        {
                            var msg = TryExtractBridgeMessage(body);
                            // 忽略"正在处理"状态的消息，继续等待最终结果
                            if (!string.IsNullOrWhiteSpace(msg) && !msg.Contains("正在处理"))
                            {
                                return msg;
                            }
                        }
                    }
                }
                catch
                {
                    // ignore
                }
                
                // 动态调整轮询间隔：前 10 秒每 200ms，之后每 500ms
                System.Threading.Thread.Sleep(i < 50 ? 200 : 500);
            }
            return null;
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
        private readonly RichTextBox _conversation;
        private readonly TextBox _input;
        private readonly Button _sendButton;
        private readonly Button _stopButton;
        private readonly Button _startButton;
        private readonly Button _pingButton;
        private readonly Button _cancelCadButton;
        private readonly Button _clearButton;
        private readonly Label _statusLabel;

        public event Action<string> SendRequested;
        public event Action StopRequested;
        public event Action StartRequested;
        public event Action PingRequested;
        public event Action CancelRequested;
        public event Action ClearRequested;

        public AIPaletteControl()
        {
            Dock = DockStyle.Fill;
            BackColor = System.Drawing.Color.FromArgb(245, 247, 250);

            var panel = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                ColumnCount = 1,
                RowCount = 6,
                Padding = new Padding(10)
            };
            panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            panel.RowStyles.Add(new RowStyle(SizeType.Percent, 62));
            panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            panel.RowStyles.Add(new RowStyle(SizeType.Percent, 30));
            panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            var title = new Label
            {
                Text = "AutoCADMindAI 助手",
                Font = new System.Drawing.Font("Microsoft YaHei UI", 10F, System.Drawing.FontStyle.Bold),
                ForeColor = System.Drawing.Color.FromArgb(35, 52, 80),
                AutoSize = true,
                Margin = new Padding(0, 0, 0, 6)
            };
            panel.Controls.Add(title, 0, 0);

            _conversation = new RichTextBox
            {
                Dock = DockStyle.Fill,
                ReadOnly = true,
                BorderStyle = BorderStyle.FixedSingle,
                BackColor = System.Drawing.Color.White,
                DetectUrls = false,
                Font = new System.Drawing.Font("Microsoft YaHei UI", 9F)
            };
            panel.Controls.Add(_conversation, 0, 1);

            var inputLabel = new Label
            {
                Text = "输入需求：",
                AutoSize = true,
                Margin = new Padding(0, 8, 0, 4)
            };
            panel.Controls.Add(inputLabel, 0, 2);

            _input = new TextBox
            {
                Multiline = true,
                AcceptsReturn = true,
                Dock = DockStyle.Fill,
                ScrollBars = ScrollBars.Vertical,
                BorderStyle = BorderStyle.FixedSingle,
                Font = new System.Drawing.Font("Microsoft YaHei UI", 9F)
            };
            _input.KeyDown += (_, e) =>
            {
                if (e.KeyCode == Keys.Enter && !e.Shift)
                {
                    e.SuppressKeyPress = true;
                    e.Handled = true;
                    var text = (_input.Text ?? string.Empty).Trim();
                    if (string.IsNullOrWhiteSpace(text))
                    {
                        SetStatus("请输入内容");
                        return;
                    }
                    SendRequested?.Invoke(text);
                }
            };
            panel.Controls.Add(_input, 0, 3);

            var btnPanel = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                ColumnCount = 3,
                RowCount = 2,
                Margin = new Padding(0, 8, 0, 6)
            };
            btnPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33.33F));
            btnPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33.33F));
            btnPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33.33F));

            _sendButton = CreateButton("发送", true);
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

            _stopButton = CreateButton("停止", false);
            _stopButton.Click += (_, __) => StopRequested?.Invoke();

            _startButton = CreateButton("启动服务", false);
            _startButton.Click += (_, __) => StartRequested?.Invoke();

            _pingButton = CreateButton("检测连接", false);
            _pingButton.Click += (_, __) => PingRequested?.Invoke();

            _cancelCadButton = CreateButton("取消CAD命令", false);
            _cancelCadButton.Click += (_, __) => CancelRequested?.Invoke();

            _clearButton = CreateButton("清空会话", false);
            _clearButton.Click += (_, __) =>
            {
                ClearRequested?.Invoke();
            };

            btnPanel.Controls.Add(_sendButton, 0, 0);
            btnPanel.Controls.Add(_stopButton, 1, 0);
            btnPanel.Controls.Add(_startButton, 2, 0);
            btnPanel.Controls.Add(_pingButton, 0, 1);
            btnPanel.Controls.Add(_cancelCadButton, 1, 1);
            btnPanel.Controls.Add(_clearButton, 2, 1);
            panel.Controls.Add(btnPanel, 0, 4);

            _statusLabel = new Label
            {
                Text = "状态：未连接",
                Dock = DockStyle.Fill,
                TextAlign = System.Drawing.ContentAlignment.MiddleLeft,
                AutoSize = false,
                Height = 22,
                BackColor = System.Drawing.Color.FromArgb(235, 240, 248),
                Padding = new Padding(6, 3, 6, 3)
            };
            panel.Controls.Add(_statusLabel, 0, 5);

            Controls.Add(panel);
            AppendSystemMessage("欢迎使用 AutoCADMindAI。建议先点击\"检测连接\"或\"启动服务\"。", false);
        }

        private static Button CreateButton(string text, bool isPrimary)
        {
            return new Button
            {
                Text = text,
                Dock = DockStyle.Fill,
                Height = 28,
                FlatStyle = FlatStyle.Flat,
                BackColor = isPrimary ? System.Drawing.Color.FromArgb(38, 122, 255) : System.Drawing.Color.White,
                ForeColor = isPrimary ? System.Drawing.Color.White : System.Drawing.Color.FromArgb(35, 52, 80)
            };
        }

        public void SetBusy(bool busy)
        {
            _sendButton.Enabled = !busy;
            _startButton.Enabled = !busy;
            _pingButton.Enabled = !busy;
        }

        public void SetStatus(string status)
        {
            _statusLabel.Text = "状态：" + status;
        }

        public void AppendUserMessage(string message)
        {
            if (string.IsNullOrWhiteSpace(message)) return;
            AppendLine("你", message, System.Drawing.Color.FromArgb(24, 85, 180));
        }

        public void AppendSystemMessage(string message, bool isError)
        {
            if (string.IsNullOrWhiteSpace(message)) return;
            AppendLine("系统", message, isError ? System.Drawing.Color.FromArgb(176, 45, 45) : System.Drawing.Color.FromArgb(60, 94, 60));
        }

        public void AppendAssistantMessage(string message)
        {
            if (string.IsNullOrWhiteSpace(message)) return;
            AppendLine("AI", message, System.Drawing.Color.FromArgb(86, 47, 150));
        }

        public void ClearInput()
        {
            _input.Clear();
            _input.Focus();
        }

        public void ClearConversation()
        {
            _conversation.Clear();
            _input.Clear();
            AppendSystemMessage("会话已清空。", false);
        }

        private void AppendLine(string role, string text, System.Drawing.Color color)
        {
            _conversation.SelectionStart = _conversation.TextLength;
            _conversation.SelectionLength = 0;
            _conversation.SelectionColor = color;
            _conversation.AppendText("[" + role + "] " + text + Environment.NewLine);
            _conversation.SelectionColor = _conversation.ForeColor;
            _conversation.ScrollToCaret();
        }
    }
}
