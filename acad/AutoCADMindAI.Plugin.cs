using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Runtime;


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

        public void Initialize()
        {
            var doc = Application.DocumentManager.MdiActiveDocument;
            var ed = doc?.Editor;
            if (ed != null)
            {
                ed.WriteMessage("\n[AutoCADMindAI] 插件初始化成功。可用命令: AIMIND, AICHAT, AISTOP");
            }
            Write("AutoCADMindAI 插件已加载。命令: AISTART, AIPING, AIMIND, AICHAT, AISTOP");
        }

        public void Terminate() { }

        [CommandMethod("AIMIND", CommandFlags.Modal)]
        public void AIMIND()
        {
            var ed = Application.DocumentManager.MdiActiveDocument?.Editor;
            ed?.WriteMessage("\n[AutoCADMindAI] AIMIND 已触发");

            // 为避免反复弹出 cmd：AIMIND 仅负责唤起，不自动拉起 Python
            if (IsBridgeAlive())
            {
                PostJson("/show", "{}");
                Write("AI窗口已唤起。", ed);
            }
            else
            {
                Write("Bridge 未就绪。请先运行 AISTART（或手动双击 start.bat）。", ed);
            }
        }

        [CommandMethod("AISTART", CommandFlags.Modal)]
        public void AISTART()
        {
            var ed = Application.DocumentManager.MdiActiveDocument?.Editor;
            if (IsBridgeAlive())
            {
                Write("Bridge 已在运行。", ed);
                return;
            }

            if (!StartPythonUi())
            {
                Write("Bridge 启动失败（启动程序未执行）。", ed);
                return;
            }

            // 非阻塞短等待，避免命令行长期卡住
            for (int i = 0; i < 15; i++)
            {
                if (IsBridgeAlive()) break;
                System.Threading.Thread.Sleep(120);
            }

            if (IsBridgeAlive())
            {
                Write("Bridge 启动成功。", ed);
                PostJson("/show", "{}");
            }
            else
            {
                Write("Bridge 未就绪。请手动双击 dist 目录下 start.bat 查看依赖报错。", ed);
            }
        }

        [CommandMethod("AIPING", CommandFlags.Modal)]
        public void AIPING()
        {
            var ed = Application.DocumentManager.MdiActiveDocument?.Editor;
            if (IsBridgeAlive())
                Write("Bridge 正常: " + BridgeBaseUrl, ed);
            else
                Write("Bridge 不可用: " + BridgeBaseUrl + "（请确认是 127.0.0.1，不是 172.0.0.1）", ed);
        }

        [CommandMethod("AICHAT", CommandFlags.Modal)]
        public void AICHAT()
        {
            var doc = Application.DocumentManager.MdiActiveDocument;
            if (doc == null) return;
            if (!IsBridgeAlive())
            {
                Write("Bridge 未就绪，请先运行 AISTART。", doc.Editor);
                return;
            }
            PostJson("/show", "{}");

            var pso = new PromptStringOptions("\n输入给 AI 的内容: ")
            {
                AllowSpaces = true
            };
            var pr = doc.Editor.GetString(pso);
            if (pr.Status != PromptStatus.OK || string.IsNullOrWhiteSpace(pr.StringResult))
                return;

            PostJson("/chat", "{\"text\":\"" + EscapeJson(pr.StringResult) + "\"}");
            Write("已发送到 AI。", doc.Editor);
        }

        [CommandMethod("AISTOP", CommandFlags.Modal)]
        public void AISTOP()
        {
            PostJson("/stop", "{}");
            Write("已请求停止。", Application.DocumentManager.MdiActiveDocument?.Editor);
        }

        [CommandMethod("AICANCEL", CommandFlags.Modal)]
        public void AICANCEL()
        {
            var doc = Application.DocumentManager.MdiActiveDocument;
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

        private static bool StartPythonUi()
        {
            var ed = Application.DocumentManager.MdiActiveDocument?.Editor;
            var pluginDir = Path.GetDirectoryName(typeof(PluginEntry).Assembly.Location) ?? Environment.CurrentDirectory;

            // 防抖：若桥接已就绪，不重复启动
            if (IsBridgeAlive()) return true;

            // 1) 优先尝试同目录下的 start.bat（隐藏窗口启动，避免卡界面）
            var startBat = Path.Combine(pluginDir, "start.bat");
            if (File.Exists(startBat))
            {
                try
                {
                    var logFile = Path.Combine(pluginDir, "bridge_start.log");
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = "cmd.exe",
                        Arguments = "/c \"\"" + startBat + "\" > \"" + logFile + "\" 2>&1\"",
                        WorkingDirectory = pluginDir,
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        WindowStyle = ProcessWindowStyle.Hidden
                    });
                    Write("已后台启动 start.bat", ed);
                    return true;
                }
                catch (System.Exception ex)
                {
                    Write("启动 start.bat 失败: " + ex.Message, ed);
                }
            }

            // 2) 其次尝试同目录 start.py + py/python 启动器
            var startPy = Path.Combine(pluginDir, "start.py");
            if (File.Exists(startPy))
            {
                try
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = "py",
                        Arguments = "\"" + startPy + "\"",
                        WorkingDirectory = pluginDir,
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        WindowStyle = ProcessWindowStyle.Hidden
                    });
                    Write("已后台通过 py 启动 start.py", ed);
                    return true;
                }
                catch { }

                try
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = "python",
                        Arguments = "\"" + startPy + "\"",
                        WorkingDirectory = pluginDir,
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        WindowStyle = ProcessWindowStyle.Hidden
                    });
                    Write("已后台通过 python 启动 start.py", ed);
                    return true;
                }
                catch (System.Exception ex)
                {
                    Write("启动 start.py 失败: " + ex.Message, ed);
                }
            }

            Write("未找到 start.bat/start.py。请将插件DLL与项目启动文件放在同一目录。", ed);
            return false;
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


        private static void Write(string message, Editor ed = null)
        {
            var editor = ed ?? Application.DocumentManager.MdiActiveDocument?.Editor;
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

}
