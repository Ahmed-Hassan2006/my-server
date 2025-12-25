import sys
import os
import webbrowser
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QLineEdit, QPushButton, QLabel, QTextEdit, QListWidget, 
    QMessageBox, QFormLayout, QStatusBar, QDialog, 
    QFileDialog, QListWidgetItem, QMenu, QInputDialog
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from github import Github, GithubException

# ========================================================
# 1. إدارة التوكن (Token Manager)
# ========================================================
TOKEN_FILE = "gh_token.txt"
CURRENT_TOKEN = ""

def load_stored_token():
    global CURRENT_TOKEN
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                token = f.read().strip()
                if token:
                    CURRENT_TOKEN = token
                    return True
        except:
            pass
    return False

def save_stored_token(token):
    global CURRENT_TOKEN
    CURRENT_TOKEN = token
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(token)

# ========================================================
# 2. حاوية العناصر المساعدة (لإخفائها عن البرنامج الرئيسي)
# ========================================================
class UIComponents:
    """
    تم وضع العناصر هنا حتى لا يراها البرنامج الرئيسي
    على أنها أدوات مستقلة لأنها ترث من QWidget
    """
    
    class AccessibleButton(QPushButton):
        def keyPressEvent(self, event):
            if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self.animateClick()
            else:
                super().keyPressEvent(event)

    class TokenDialog(QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("إعدادات التوكن")
            self.resize(400, 200)
            self.setLayoutDirection(Qt.RightToLeft)
            layout = QVBoxLayout(self)
            
            lbl = QLabel("الرجاء إدخال رمز الوصول الشخصي (Token) الخاص بحساب GitHub:")
            lbl.setWordWrap(True)
            layout.addWidget(lbl)
            
            self.token_input = QLineEdit()
            self.token_input.setPlaceholderText("ghp_xxxxxxxxxxxxxxxxxxxxxx")
            self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
            layout.addWidget(self.token_input)
            
            # استخدام الزر من نفس الحاوية
            btn_save = UIComponents.AccessibleButton("حفظ ومتابعة")
            btn_save.clicked.connect(self.save_and_close)
            layout.addWidget(btn_save)

        def save_and_close(self):
            t = self.token_input.text().strip()
            if t:
                save_stored_token(t)
                self.accept()
            else:
                QMessageBox.warning(self, "تنبيه", "يجب إدخال التوكن")

    class RepoInfoDialog(QDialog):
        def __init__(self, parent, current_name, current_desc):
            super().__init__(parent)
            self.setWindowTitle("تعديل بيانات المستودع")
            self.resize(500, 300)
            self.setLayoutDirection(Qt.RightToLeft)
            l = QFormLayout(self)
            
            self.name_edit = QLineEdit(current_name)
            self.desc_edit = QTextEdit(current_desc)
            self.desc_edit.setMaximumHeight(80)
            self.desc_edit.setTabChangesFocus(True)
            
            l.addRow("اسم المستودع:", self.name_edit)
            l.addRow("الوصف:", self.desc_edit)
            
            btn = UIComponents.AccessibleButton("حفظ التعديلات")
            btn.clicked.connect(self.accept)
            l.addRow(btn)

    class EditorDialog(QDialog):
        def __init__(self, parent, filename, content_bytes=b""):
            super().__init__(parent)
            self.setWindowTitle(f"تعديل: {filename}")
            self.resize(700, 500)
            self.setLayoutDirection(Qt.RightToLeft)
            
            layout = QVBoxLayout(self)
            self.text_area = QTextEdit()
            
            try:
                text_str = content_bytes.decode('utf-8')
                self.text_area.setPlainText(text_str)
            except:
                self.text_area.setPlainText("ملف غير نصي")
                self.text_area.setReadOnly(True)

            self.text_area.setTabChangesFocus(True)
            layout.addWidget(self.text_area)

            btn_save = UIComponents.AccessibleButton("حفظ وإنهاء")
            btn_save.clicked.connect(self.accept)
            layout.addWidget(btn_save)

        def get_content_bytes(self):
            return self.text_area.toPlainText().encode('utf-8')

# ========================================================
# 3. المحرك الخلفي (Worker) - آمن لأنه يرث QThread
# ========================================================
class GitHubWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, task, **kwargs):
        super().__init__()
        self.task = task
        self.kwargs = kwargs

    def run(self):
        if not CURRENT_TOKEN:
            self.error.emit("لم يتم العثور على توكن. يرجى إدخاله.")
            return

        try:
            g = Github(CURRENT_TOKEN)
            user = g.get_user()

            if self.task == "list_repos":
                repos = list(user.get_repos(sort="updated", direction="desc"))
                self.finished.emit(repos)

            elif self.task == "list_files":
                repo = g.get_repo(self.kwargs['full_name'])
                path = self.kwargs['path']
                try:
                    contents = repo.get_contents(path) if path else repo.get_contents("")
                    if not isinstance(contents, list): contents = [contents]
                    self.finished.emit(contents)
                except GithubException as e:
                    if e.status == 404: self.finished.emit([]) 
                    else: raise e

            elif self.task == "upload_file":
                repo = g.get_repo(self.kwargs['full_name'])
                path = self.kwargs['path']
                content = self.kwargs['content']
                msg = self.kwargs.get('msg', "Uploaded via Tool")
                try:
                    existing = repo.get_contents(path)
                    repo.update_file(existing.path, msg, content, existing.sha)
                    self.finished.emit(f"تم تحديث الملف: {path}")
                except:
                    repo.create_file(path, msg, content)
                    self.finished.emit(f"تم إنشاء الملف: {path}")

            elif self.task == "delete_file":
                repo = g.get_repo(self.kwargs['full_name'])
                file_obj = repo.get_contents(self.kwargs['path'])
                repo.delete_file(file_obj.path, "Deleted", file_obj.sha)
                self.finished.emit("تم الحذف بنجاح")

            elif self.task == "read_file":
                repo = g.get_repo(self.kwargs['full_name'])
                file_obj = repo.get_contents(self.kwargs['path'])
                self.finished.emit((file_obj.decoded_content, file_obj.sha))

            elif self.task == "create_repo":
                user.create_repo(self.kwargs['name'], private=self.kwargs['private'], auto_init=True)
                self.finished.emit("تم إنشاء المستودع")

            elif self.task == "delete_repo":
                repo = g.get_repo(self.kwargs['full_name'])
                repo.delete()
                self.finished.emit("تم حذف المستودع")

            elif self.task == "edit_repo_info":
                repo = g.get_repo(self.kwargs['full_name'])
                repo.edit(name=self.kwargs['new_name'], description=self.kwargs['new_desc'])
                self.finished.emit("تم تحديث بيانات المستودع بنجاح")

            elif self.task == "toggle_privacy":
                repo = g.get_repo(self.kwargs['full_name'])
                new_state = not repo.private
                repo.edit(private=new_state)
                state_txt = "خاص" if new_state else "عام"
                self.finished.emit(f"تم تحويل المستودع إلى {state_txt}")

            elif self.task == "move_file_to_folder":
                repo = g.get_repo(self.kwargs['full_name'])
                old_path = self.kwargs['old_path']
                new_folder = self.kwargs['new_folder']
                filename = self.kwargs['filename']

                old_file = repo.get_contents(old_path)
                content = old_file.decoded_content
                
                parent_dir = os.path.dirname(old_path)
                if parent_dir:
                    final_new_path = f"{parent_dir}/{new_folder}/{filename}"
                else:
                    final_new_path = f"{new_folder}/{filename}"

                repo.create_file(final_new_path, f"Moved to {new_folder}", content)
                repo.delete_file(old_path, f"Moved to {new_folder}", old_file.sha)
                self.finished.emit(f"تم نقل {filename} إلى المجلد {new_folder}")

        except Exception as e:
            self.error.emit(str(e))

# ========================================================
# 4. الواجهة الرئيسية - هذا هو الكلاس الوحيد المكشوف
# ========================================================
class GitHubToolV14(QWidget):
    
    TOOL_NAME = "أداة التحكم في GitHub"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GitHub Tool V14")
        self.resize(1100, 750)
        self.setLayoutDirection(Qt.RightToLeft)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.status_bar = QStatusBar()
        self.clipboard = QApplication.clipboard()

        if not load_stored_token():
            self.change_token_dialog()

        self.current_repo_data = None
        self.current_path = "" 

        central = QWidget()
        layout = QHBoxLayout(central)
        self.main_layout.addWidget(central)

        # --- يمين ---
        right = QWidget()
        r_lay = QVBoxLayout(right)
        r_lay.addWidget(QLabel("المستودعات:"))
        
        self.repo_list = QListWidget()
        self.repo_list.setAccessibleName("قائمة المستودعات")
        self.repo_list.itemActivated.connect(self.open_repo)
        self.repo_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.repo_list.customContextMenuRequested.connect(self.repo_menu)
        r_lay.addWidget(self.repo_list)

        # استخدام الأزرار من الحاوية UIComponents
        btn_ref = UIComponents.AccessibleButton("تحديث القائمة")
        btn_ref.clicked.connect(self.load_repos)
        r_lay.addWidget(btn_ref)

        btn_new_repo = UIComponents.AccessibleButton("إنشاء مستودع جديد")
        btn_new_repo.clicked.connect(self.dialog_create_repo)
        r_lay.addWidget(btn_new_repo)

        btn_token = UIComponents.AccessibleButton("تعديل التوكن")
        btn_token.clicked.connect(self.change_token_dialog)
        r_lay.addWidget(btn_token)

        layout.addWidget(right, 1)

        # --- يسار ---
        self.left = QWidget()
        self.left.setEnabled(False)
        l_lay = QVBoxLayout(self.left)
        
        self.lbl_repo = QLabel("...")
        self.lbl_repo.setStyleSheet("color: blue; font-weight: bold;")
        l_lay.addWidget(self.lbl_repo)

        nav = QHBoxLayout()
        btn_up = UIComponents.AccessibleButton("رجوع للخلف")
        btn_up.clicked.connect(self.go_up)
        nav.addWidget(btn_up)
        self.lbl_path = QLabel("/")
        nav.addWidget(self.lbl_path)
        l_lay.addLayout(nav)

        self.file_list = QListWidget()
        self.file_list.setAccessibleName("قائمة الملفات")
        self.file_list.itemActivated.connect(self.on_file_enter)
        self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self.file_menu)
        l_lay.addWidget(self.file_list)

        btns = QHBoxLayout()
        self.btn_upl = UIComponents.AccessibleButton("رفع ملف")
        self.btn_upl.clicked.connect(self.upload_file_dialog)
        btns.addWidget(self.btn_upl)

        self.btn_cr_txt = UIComponents.AccessibleButton("ملف نصي")
        self.btn_cr_txt.clicked.connect(self.create_text_dialog)
        btns.addWidget(self.btn_cr_txt)
        l_lay.addLayout(btns)
        
        self.btn_del = UIComponents.AccessibleButton("حذف المحدد")
        self.btn_del.setStyleSheet("color: red;")
        self.btn_del.clicked.connect(self.delete_current_item)
        l_lay.addWidget(self.btn_del)

        layout.addWidget(self.left, 2)
        self.main_layout.addWidget(self.status_bar)

        self.shortcut = QShortcut(QKeySequence(Qt.Key_Space), self.repo_list)
        self.shortcut.activated.connect(lambda: self.open_repo(self.repo_list.currentItem()))

        if CURRENT_TOKEN:
            self.load_repos()

    # ==========================================
    # استدعاء النوافذ من الحاوية
    # ==========================================
    def change_token_dialog(self):
        d = UIComponents.TokenDialog(self)
        if d.exec():
            self.load_repos()

    def edit_repo_details(self, repo):
        dlg = UIComponents.RepoInfoDialog(self, current_name=repo.name, current_desc=repo.description or "")
        if dlg.exec():
            new_name = dlg.name_edit.text()
            new_desc = dlg.desc_edit.toPlainText()
            self.run_worker("edit_repo_info", lambda m: (QMessageBox.information(self, "تم", m), self.load_repos()),
                            full_name=repo.full_name, new_name=new_name, new_desc=new_desc)

    def create_text_dialog(self):
        name, ok = QInputDialog.getText(self, "ملف نصي", "اسم الملف:")
        if ok and name:
            dlg = UIComponents.EditorDialog(self, name)
            if dlg.exec():
                content_bytes = dlg.get_content_bytes()
                path_sep = "/" if self.current_path else ""
                gh_path = f"{self.current_path}{path_sep}{name}"

                self.run_worker("upload_file",
                                lambda m: (self.status_bar.showMessage(m), self.load_files()),
                                full_name=self.current_repo_data.full_name,
                                path=gh_path,
                                content=content_bytes,
                                msg=f"Create {name}")

    def show_editor(self, filename, content_bytes):
        dlg = UIComponents.EditorDialog(self, filename, content_bytes)
        if dlg.exec():
            new_bytes = dlg.get_content_bytes()
            path_sep = "/" if self.current_path else ""
            gh_path = f"{self.current_path}{path_sep}{filename}"
            
            self.run_worker("upload_file",
                            lambda m: (self.status_bar.showMessage(m), self.load_files()),
                            full_name=self.current_repo_data.full_name,
                            path=gh_path,
                            content=new_bytes,
                            msg=f"Update {filename}")

    # ==========================================
    # باقي الوظائف (لم تتغير)
    # ==========================================
    def run_worker(self, task, on_finish, **kwargs):
        self.status_bar.showMessage("جاري التنفيذ...")
        self.w = GitHubWorker(task, **kwargs)
        self.w.finished.connect(on_finish)
        self.w.error.connect(self.on_error)
        self.w.start()

    def on_error(self, err):
        self.status_bar.showMessage("فشل")
        QMessageBox.critical(self, "خطأ", f"حدثت مشكلة:\n{err}")

    def load_repos(self):
        if not CURRENT_TOKEN: return
        self.repo_list.clear()
        self.run_worker("list_repos", self.display_repos)

    def display_repos(self, repos):
        self.repo_list.clear()
        for r in repos:
            visibility = "خاص" if r.private else "عام"
            item = QListWidgetItem(f"{r.name} - {visibility}")
            item.setData(Qt.UserRole, r)
            self.repo_list.addItem(item)
        self.status_bar.showMessage(f"تم تحميل {len(repos)} مستودع")
        self.repo_list.setFocus()

    def open_repo(self, item):
        if not item: return
        repo = item.data(Qt.UserRole)
        self.current_repo_data = repo
        self.left.setEnabled(True)
        self.lbl_repo.setText(f"المستودع النشط: {repo.name}")
        self.current_path = ""
        self.load_files()

    def dialog_create_repo(self):
        name, ok = QInputDialog.getText(self, "جديد", "اسم المستودع:")
        if ok and name:
            self.run_worker("create_repo", lambda m: (QMessageBox.information(self,"تم",m), self.load_repos()), 
                            name=name, private=False)

    def delete_repo_act(self, repo):
        if QMessageBox.question(self, "حذف", f"هل أنت متأكد من حذف المستودع {repo.name}؟") == QMessageBox.Yes:
            self.run_worker("delete_repo", lambda m: (QMessageBox.information(self,"تم",m), self.load_repos(), self.left.setEnabled(False)), 
                            full_name=repo.full_name)

    def toggle_repo_privacy(self, repo):
        current_status = "خاص" if repo.private else "عام"
        msg = f"المستودع حالياً ({current_status}). هل تريد عكس الحالة؟"
        if QMessageBox.question(self, "تغيير الخصوصية", msg) == QMessageBox.Yes:
            self.run_worker("toggle_privacy", lambda m: (QMessageBox.information(self, "تم", m), self.load_repos()),
                            full_name=repo.full_name)

    def load_files(self):
        self.lbl_path.setText(f"/{self.current_path}")
        self.file_list.clear()
        self.file_list.addItem("جاري التحميل...")
        self.run_worker("list_files", self.display_files, full_name=self.current_repo_data.full_name, path=self.current_path)

    def display_files(self, contents):
        self.file_list.clear()
        if not contents:
            self.file_list.addItem("المجلد فارغ")
            return
        
        contents.sort(key=lambda x: (x.type != "dir", x.name))
        for c in contents:
            type_txt = "مجلد" if c.type == "dir" else "ملف"
            item = QListWidgetItem(f"{c.name} ({type_txt})")
            item.setData(Qt.UserRole, c)
            self.file_list.addItem(item)
        self.status_bar.showMessage(f"عدد العناصر: {len(contents)}")

    def on_file_enter(self, item):
        obj = item.data(Qt.UserRole)
        if not obj: return

        if obj.type == "dir":
            path_sep = "/" if self.current_path else ""
            self.current_path = f"{self.current_path}{path_sep}{obj.name}"
            self.load_files()
        else:
            self.run_worker("read_file", 
                            lambda res: self.show_editor(obj.name, res[0]), 
                            full_name=self.current_repo_data.full_name, path=obj.path)

    def go_up(self):
        if "/" in self.current_path:
            self.current_path = self.current_path.rsplit("/", 1)[0]
        else:
            self.current_path = ""
        self.load_files()

    def upload_file_dialog(self):
        if not self.current_repo_data: return
        fpath, _ = QFileDialog.getOpenFileName(self, "اختر ملفاً")
        if fpath:
            try:
                with open(fpath, "rb") as f: content = f.read()
                filename = os.path.basename(fpath)
                path_sep = "/" if self.current_path else ""
                gh_path = f"{self.current_path}{path_sep}{filename}"

                self.run_worker("upload_file", 
                                lambda m: (QMessageBox.information(self,"نجاح", m), self.load_files()),
                                full_name=self.current_repo_data.full_name,
                                path=gh_path,
                                content=content,
                                msg=f"Upload {filename}")
            except Exception as e:
                self.on_error(str(e))

    def delete_current_item(self):
        item = self.file_list.currentItem()
        if not item: 
            QMessageBox.warning(self, "تنبيه", "حدد عنصراً أولاً")
            return
        obj = item.data(Qt.UserRole)
        if not obj: return
        self.delete_file_act(obj)

    def delete_file_act(self, obj):
        if QMessageBox.question(self, "حذف", f"هل أنت متأكد من حذف {obj.name}؟") == QMessageBox.Yes:
            self.run_worker("delete_file", lambda m: self.load_files(),
                            full_name=self.current_repo_data.full_name, path=obj.path)

    def move_file_to_new_folder(self, obj):
        folder_name, ok = QInputDialog.getText(self, "إنشاء مجلد ونقل", "اكتب اسم المجلد الجديد:")
        if ok and folder_name:
            self.run_worker("move_file_to_folder", 
                            lambda m: (QMessageBox.information(self, "نجاح", m), self.load_files()),
                            full_name=self.current_repo_data.full_name,
                            old_path=obj.path,
                            new_folder=folder_name,
                            filename=obj.name)

    def repo_menu(self, pos):
        item = self.repo_list.itemAt(pos)
        if not item: return
        repo = item.data(Qt.UserRole)
        
        m = QMenu()
        m.addAction("فتح").triggered.connect(lambda: self.open_repo(item))
        m.addSeparator()
        
        m.addAction("تعديل الاسم والوصف").triggered.connect(lambda: self.edit_repo_details(repo))
        m.addAction("تغيير الخصوصية").triggered.connect(lambda: self.toggle_repo_privacy(repo))
        
        m.addSeparator()
        m.addAction("فتح في المتصفح").triggered.connect(lambda: webbrowser.open(repo.html_url))
        m.addAction("نسخ رابط الاستنساخ").triggered.connect(lambda: self.clipboard.setText(repo.clone_url))
        m.addSeparator()
        m.addAction("حذف المستودع").triggered.connect(lambda: self.delete_repo_act(repo))
        
        m.exec(self.repo_list.mapToGlobal(pos))

    def file_menu(self, pos):
        item = self.file_list.itemAt(pos)
        if not item: return
        obj = item.data(Qt.UserRole)
        if not obj: return
        
        m = QMenu()
        
        if obj.type != "dir":
            m.addAction("تعديل الملف").triggered.connect(lambda: self.on_file_enter(item))
            m.addAction("إنشاء مجلد ونقل الملف إليه").triggered.connect(lambda: self.move_file_to_new_folder(obj))
            m.addSeparator()
            m.addAction("نسخ رابط التحميل").triggered.connect(lambda: self.clipboard.setText(obj.download_url))
        else:
            m.addAction("دخول المجلد").triggered.connect(lambda: self.on_file_enter(item))
            
        m.addSeparator()
        m.addAction("فتح في المتصفح").triggered.connect(lambda: webbrowser.open(obj.html_url))
        m.addAction("حذف").triggered.connect(lambda: self.delete_file_act(obj))
        
        m.exec(self.file_list.mapToGlobal(pos))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    font = app.font(); font.setPointSize(12); app.setFont(font)
    try:
        win = GitHubToolV14()
        win.show()
        sys.exit(app.exec())
    except Exception as e:
        print(e)