import os
import sys

from PyQt5 import uic
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QTextCursor, QIntValidator
from PyQt5.QtWidgets import QWidget, QApplication, QLineEdit, QTextEdit, QPushButton, QMessageBox
from gurux_dlms import GXUInt16
from gurux_dlms.enums import DataType
from gurux_dlms.objects import GXDLMSData

from libs.configur import server, login, folder, password
from libs.connect import connect


class EmittingStream(QObject):
    textWritten = pyqtSignal(str)

    def write(self, text):
        self.textWritten.emit(str(text))

    def flush(self):
        pass  # Необходимо для совместимости с sys.stdout


class FileUploader(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        current_dir = os.path.dirname(__file__)
        ui_path = os.path.join(current_dir, 'libs', 'maket.ui')

        uic.loadUi(ui_path, self)

        self.number_com = self.findChild(QLineEdit, 'enter_com')
        self.number_com.setValidator(QIntValidator())

        self.start = self.findChild(QPushButton, 'start_button')
        self.start.clicked.connect(self.start_command)

        self.text_edit = self.findChild(QTextEdit, 'textEdit')
        self.text_edit.setReadOnly(True)  # Запрещаем редактирование
        self.redirect_stdout()
        self.stream.textWritten.connect(self.on_text_written)

        self.applyDarkTheme()

    def start_command(self):
        self.text_edit.clear()
        if not self.number_com.text().strip():
            # Показываем предупреждение
            QMessageBox.warning(
                self,
                "Предупреждение",
                "Введите COM соединения!",
                QMessageBox.Ok
            )
            return

        com = self.number_com.text()
        reader, settings = connect(com)
        try:
            settings.media.open()
            reader.initializeConnection()

            self.set_ftp(reader)

            self.set_harm(reader)

            reader.close()
        except Exception as e:
            settings.media.close()
            self.update_text(f"Ошибка {e}.", "red")
            print()
            self.update_text(f"Проверьте настройки.", "red")


    def set_harm(self, reader):
        data = GXDLMSData('0.0.2.164.6.255')
        try:
            new_arrays = reader.read(data, 2)
            data.setDataType(2, DataType.STRUCTURE)

            for z in range(6):
                for i in range(30):
                    if z in [0, 1, 2]:
                        if i == 10:
                            new_arrays[z][i] = GXUInt16(17)
                        elif i == 12:
                            new_arrays[z][i] = GXUInt16(14)
                        else:
                            new_arrays[z][i] = GXUInt16(65535)
                    else:
                        new_arrays[z][i] = GXUInt16(65535)

            data.value = new_arrays
            reader.write(data, 2)

            actual_arrays = reader.read(data, 2)

            with open('test.txt', 'w', encoding='utf-8') as file:
                    file.write(actual_arrays)

            try:
                for z in range(6):
                    for i in range(30):
                        if z in [0, 1, 2]:
                            if i == 10:
                                assert new_arrays[z][i] == 17
                            elif i == 12:
                                assert new_arrays[z][i] == GXUInt16(14)
                            else:
                                assert new_arrays[z][i] == GXUInt16(65535)
                        else:
                            assert  new_arrays[z][i] == GXUInt16(65535)
            except AssertionError as e:
                self.update_text(f"Ошибка при записи гармоники с координатами "
                                 f"[структура №{z + 1}- строчка №{i + 1}] >> {e}", "red")

        except Exception as e:
            self.update_text(f"Ошибка при записи гармоники >> {e}", "red")


    def set_ftp(self, reader):
        try:
            ftp_server = GXDLMSData('0.0.2.164.1.255')
            ftp_server_login = GXDLMSData('0.0.2.164.2.255')
            ftp_server_password = GXDLMSData('0.0.2.164.3.255')
            ftp_server_folder = GXDLMSData('0.0.2.164.4.255')

            ftp_server.value = server
            ftp_server.setDataType(2, DataType.STRING)

            ftp_server_login.value = login
            ftp_server_login.setDataType(2, DataType.STRING)

            ftp_server_password.value = password
            ftp_server_password.setDataType(2, DataType.STRING)

            ftp_server_folder.value = folder
            ftp_server_folder.setDataType(2, DataType.STRING)

            self.write_value(ftp_server_password, reader)
            self.write_value(ftp_server, reader)
            self.write_value(ftp_server_login, reader)
            self.write_value(ftp_server_folder, reader)

            set_server = reader.read(ftp_server, 2)
            set_login = reader.read(ftp_server_login, 2)
            set_folder = reader.read(ftp_server_folder, 2)
            set_password = reader.read(ftp_server_password, 2)

            self.update_text(f"Установленное значение server [{ftp_server.logicalName}] = {set_server}.", "green")
            self.update_text(f"Установленное значение login [{ftp_server_login.logicalName}] = {set_login}.", "green")
            self.update_text(f"Установленное значение folder [{ftp_server_folder.logicalName}] = {set_folder}.", "green")
            self.update_text(f"Установленное значение password [{ftp_server_password.logicalName}] = {set_password}.",
                         "green")
        except Exception as e:
            self.update_text(f"Ошибка при записи параметров FTP >> {e}", "red")

    def write_value(self, data, reader):
        try:
            reader.write(data, 2)
        except Exception as e:
            self.update_text(f'Объект {data.logicalName}, "не записался, ошибка >> {e}', "red")

    def update_text(self, message, color):
        self.text_edit.append(f"\n<font color={color} size='4'>{message}</font>\n")

    def redirect_stdout(self):
        self.stream = EmittingStream()
        sys.stdout = self.stream
        sys.stderr = self.stream

    def on_text_written(self, text):
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.text_edit.setTextCursor(cursor)
        self.text_edit.ensureCursorVisible()
        QApplication.processEvents()

    def applyDarkTheme(self):
        # Определяем стили для темной темы
        dark_stylesheet = """
        QWidget {
            background-color: #2c313c;
            color: #ffffff;
        }

        QLineEdit {
            background-color: #363d47;
            color: #ffffff;
            border: 1px solid #444950;
            border-radius: 4px;
            padding: 5px;
        }

        QLineEdit:focus {
            border: 1px solid #61dafb;
        }

        QPushButton {
            background-color: #363d47;
            color: #ffffff;
            border: 1px solid #444950;
            border-radius: 4px;
            padding: 5px 10px;
        }

        QPushButton:hover {
            background-color: #444950;
        }

        QPushButton:pressed {
            background-color: #2c313c;
        }
        """

        # Применяем стиль к приложению
        self.setStyleSheet(dark_stylesheet)


def main():
    app = QApplication(sys.argv)
    ex = FileUploader()
    ex.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
