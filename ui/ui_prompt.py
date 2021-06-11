from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

def make_dialog(title, message, buttons, icon=QMessageBox.Information, message_extra="", parent=None):
  msg = QMessageBox(parent)
  msg.setIcon(icon)

  msg.setText(message)
  if(message_extra):
    msg.setInformativeText(message_extra)
  msg.setWindowTitle(title)
  msg.setStandardButtons(buttons)
	
  return msg

def show_error(title, message, message_extra="", parent=None):
  return make_dialog(title, message, QMessageBox.Ok, QMessageBox.Critical, message_extra=message_extra, parent=parent).exec_()

def show_dialog(title, message, message_extra="", parent=None):
  return make_dialog(title, message, QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Information, message_extra=message_extra, parent=parent).exec_()

def show_prompt(title, message, message_extra="", parent=None):
  return make_dialog(title, message, QMessageBox.Yes | QMessageBox.No, QMessageBox.Information, message_extra=message_extra, parent=parent).exec_()

def show_prompt_3(title, message, message_extra="", parent=None):
  return make_dialog(title, message, QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Information, message_extra=message_extra, parent=parent).exec_()


def show_number_prompt(title, message, min=1, max=1000, step=1, parent=None):
  return QInputDialog.getInt(parent, title, message, min=min, max=max, step=step)

def show_hard_delete_prompt(parent=None):
  hard_delete_dialog = make_dialog("Delete Trade?", "How would you like to delete the trade?", QMessageBox.Cancel, message_extra=\
      "Soft-Delete: Trade is only deleted locally, signed partials already publicised can't be recalled. Use this if you plan on immediately posting an updated trade.\r\n\r\n"+
      "Hard-Delete: Trade is deleted locally and UTXO's are invalidated by sending to yourself. Use this if you don't want any parties to be able to execute a previously publicised signed partial.", parent=parent)
  hard_delete_dialog.addButton("Soft-Delete", QMessageBox.DestructiveRole)
  hard_delete_dialog.addButton("Hard-Delete", QMessageBox.YesRole)

  return hard_delete_dialog.exec_()


def show_hard_delete_type_prompt(parent=None):
  hard_delete_dialog = make_dialog("Hard-Delete Method", "How would you like to transfer the assets to yourself?", QMessageBox.Cancel, message_extra=\
      "Grouped: You send all aseets to a single output UTXO, smaller transaction, but likely need to set up again in the future.\r\n\r\n"+
      "Identical: You send all assets in the same quantities they are now, larger transaction, but allows simple reuse of that quantity.", parent=parent)
  hard_delete_dialog.addButton("Identical", QMessageBox.DestructiveRole)
  hard_delete_dialog.addButton("Grouped", QMessageBox.YesRole)

  return hard_delete_dialog.exec_()