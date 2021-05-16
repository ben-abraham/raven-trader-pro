from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, json, time, getpass, os.path
from config import *

#
#Helper function
#

def make_transfer(name, quantity):
  return {"transfer":{name:quantity}}

def show_error(title, message, message_extra="", parent=None):
  msg = QMessageBox(parent)
  msg.setIcon(QMessageBox.Critical)

  msg.setText(message)
  if(message_extra):
    msg.setInformativeText(message_extra)
  msg.setWindowTitle(title)
  msg.setStandardButtons(QMessageBox.Ok)
	
  return msg.exec_()

def show_dialog(title, message, message_extra="", parent=None):
  msg = QMessageBox(parent)
  msg.setIcon(QMessageBox.Information)

  msg.setText(message)
  if(message_extra):
    msg.setInformativeText(message_extra)
  msg.setWindowTitle(title)
  msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
	
  return msg.exec_()

#
#Helper Classes
#

class QTwoLineRowWidget (QWidget):
  def __init__ (self, parent = None):
    super(QTwoLineRowWidget, self).__init__(parent)
    self.textQVBoxLayout = QVBoxLayout()
    self.textUpQLabel    = QLabel()
    self.textDownQLabel  = QLabel()
    self.textQVBoxLayout.addWidget(self.textUpQLabel)
    self.textQVBoxLayout.addWidget(self.textDownQLabel)
    self.allQHBoxLayout  = QHBoxLayout()
    self.iconQLabel      = QLabel()
    self.allQHBoxLayout.addWidget(self.iconQLabel, 0)
    self.allQHBoxLayout.addLayout(self.textQVBoxLayout, 1)
    self.setLayout(self.allQHBoxLayout)
    # setStyleSheet
    self.textUpQLabel.setStyleSheet('''
        color: rgb(0, 0, 255);
    ''')
    self.textDownQLabel.setStyleSheet('''
        color: rgb(255, 0, 0);
    ''')
   

  @staticmethod
  def from_swap(swap, **kwargs):
    row = QTwoLineRowWidget()
    row.swap = swap
    if swap.type == "buy":
      row.setTextUp("{} {:.8g}x [{}] for {:.8g} RVN ({:.8g} each)".format(
        "Buy" if swap.own else "Sold", swap.quantity, swap.asset, swap.totalPrice(), swap.unit_price))
    else:
      row.setTextUp("{} {:.8g}x [{}] for {:.8g} RVN ({:.8g} each)".format(
        "Sell" if swap.own else "Bought", swap.quantity, swap.asset, swap.totalPrice(), swap.unit_price))
    if swap.state == "completed":
      if not swap.own:
        row.setTextDown("Completed: {}".format(swap.txid))
      else:
        row.setTextDown("Executed: {}".format(swap.txid))
    elif swap.state == "removed":
      row.setTextDown("Removed")
    return row

  @staticmethod
  def from_vout(vout, ismine):
    row = QTwoLineRowWidget()
    row.vout = vout
    row.ismine = ismine
    
    spk = vout["scriptPubKey"]

    if(spk["type"] == "transfer_asset"):
      row.setTextUp("{}x [{}]".format(spk["asset"]["amount"],spk["asset"]["name"]))
    else:
      row.setTextUp("{} RVN".format(row.vout["value"]))
    
    if(ismine):
      row.setTextDown("** {}".format(spk["addresses"][0]))
    else:  
      row.setTextDown(spk["addresses"][0])

    return row

  def getSwap (self):
    return self.swap

  def setTextUp (self, text):
    self.textUpQLabel.setText(text)

  def setTextDown (self, text):
    self.textDownQLabel.setText(text)

  def setIcon (self, imagePath):
    self.iconQLabel.setPixmap(QPixmap(imagePath))