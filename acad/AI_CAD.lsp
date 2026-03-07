;;; AI CAD Plugin for AutoCAD
;;; 加载AI CAD插件

(defun c:AI_CAD ()
  (setq python_exe "e:\\user\\桌面\\AutoOffice\\venv\\Scripts\\python.exe")
  (setq main_script "e:\\user\\桌面\\AutoOffice\\main_ai_cad.py")
  
  (if (and (findfile python_exe)
           (findfile main_script))
      (
        (startapp python_exe main_script)
        (princ "\nAI CAD插件已启动")
      )
      (
        (princ "\n错误：无法找到Python执行文件或主脚本")
      )
  )
  (princ)
)

;;; 添加到AutoCAD菜单
(vl-load-com)
(defun add-to-menu ()
  (setq acad (vlax-get-acad-object))
  (setq doc (vla-get-ActiveDocument acad))
  (setq menubar (vla-get-MenuBar doc))
  
  ;; 尝试添加到工具菜单
  (setq tools_menu (vla-item menubar "Tools"))
  (if (not (vlax-null tools_menu))
      (
        (vla-AddMenuItem 
          tools_menu
          (vla-get-Count tools_menu)
          "AI CAD"
          "^C^C(AI_CAD)"
        )
      )
  )
)

;;; 自动加载
(add-to-menu)
(princ "\nAI CAD插件已加载，输入 AI_CAD 命令启动")
(princ)
