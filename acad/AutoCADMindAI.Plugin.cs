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
            AppendStartupLog("C#", "AIMIND command triggered.");

            if (EnsureBridgeReady(ed))
            {
                PostJson("/show", "{}");
                Write("AI 窗口已就绪，你可以直接输入需求。", ed);
                AppendStartupLog("C#", "AIMIND flow ready: bridge alive and /show posted.");
            }
        }

        [CommandMethod("AISTART", CommandFlags.Modal)]
        public void AISTART()
        {
            var ed = Application.DocumentManager.MdiActiveDocument?.Editor;
            Write("AISTART 为开发者调试命令。普通用户请直接使用 AIMIND。", ed);

            if (EnsureBridgeReady(ed))
            {
                Write("Bridge 启动完成（开发者模式）。", ed);
            }
        }

        [CommandMethod("AIPING", CommandFlags.Modal)]
        public void AIPING()
        {
            var ed = Application.DocumentManager.MdiActiveDocument?.Editor;
            Write("AIPING 为开发者调试命令。普通用户请直接使用 AIMIND。", ed);

            if (IsBridgeAlive())
                Write("Bridge 正常: " + BridgeBaseUrl, ed);
            else
                Write("Bridge 不可用: " + BridgeBaseUrl + "（请确认地址是 127.0.0.1）。", ed);
        }

        [CommandMethod("AICHAT", CommandFlags.Modal)]
        public void AICHAT()
        {
            var doc = Application.DocumentManager.MdiActiveDocument;
            if (doc == null) return;
            if (!EnsureBridgeReady(doc.Editor))
            {
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
            var ed = Application.DocumentManager.MdiActiveDocument?.Editor;
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
