from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

def show_dialog_inner(title, message, buttons, icon=QMessageBox.Information, message_extra="", parent=None):
  msg = QMessageBox(parent)
  msg.setIcon(icon)

  msg.setText(message)
  if(message_extra):
    msg.setInformativeText(message_extra)
  msg.setWindowTitle(title)
  msg.setStandardButtons(buttons)
	
  return msg.exec_()

def show_error(title, message, message_extra="", parent=None):
  return show_dialog_inner(title, message, QMessageBox.Ok, QMessageBox.Critical, message_extra=message_extra, parent=parent)

def show_dialog(title, message, message_extra="", parent=None):
  return show_dialog_inner(title, message, QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Information, message_extra=message_extra, parent=parent)

def show_prompt(title, message, message_extra="", parent=None):
  return show_dialog_inner(title, message, QMessageBox.Yes | QMessageBox.No, QMessageBox.Information, message_extra=message_extra, parent=parent)

def show_prompt_3(title, message, message_extra="", parent=None):
  return show_dialog_inner(title, message, QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Information, message_extra=message_extra, parent=parent)


def show_number_prompt(title, message, min=1, max=1000, step=1, parent=None):
  return QInputDialog.getInt(parent, title, message, min=min, max=max, step=step)