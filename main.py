from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, time, getpass, os.path

from ui.main_window import MainWindow

from app_settings import AppSettings
from app_instance import AppInstance

from util import *
from rvn_rpc import *

## Main app entry point
if __name__ == "__main__":
  #Settings need to be loaded seperately
  AppInstance.settings = AppSettings()
  first_launch = AppInstance.settings.on_load()

  app = QApplication(sys.argv)

  if test_rpc_status(first_launch):
    AppInstance.on_init()
    #Finally init/run main window
    window = MainWindow()
    window.show()
    
    error = None
    try:
      app.exec_()
    except (Exception) as e:
      error = e
    
    AppInstance.on_exit(error)
