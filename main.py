from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, time, getpass, os.path, logging, threading
from multiprocessing import Process, Value, Array, Queue
from multiprocessing.managers import BaseManager

from ui.main_window import MainWindow

from app_settings import AppSettings
from app_instance import AppInstance

from util import *
from rvn_rpc import *

global window

AppInstance.setup_logging() #First things first :)

class AppManager(BaseManager): pass

def on_launch(window, args):
  logging.info("Test")
  (url) = args[0]
  logging.info("On Launch: {}".format(url))
  logging.info("{}, {}".format(threading.get_ident(), threading.main_thread().ident))
  logging.info("window" in AppInstance.__class__.__dict__)
  #window.on_url_handled(args[0])

class LaunchWorker(QObject):
  messaged = pyqtSignal(str)

  def __init__(self):
    super().__init__()
    #Handle multi-process registration code.
    self.app_mgr = AppManager(address=('127.0.0.1', 50505), authkey=b'raventraderpro')
    self.app_mgr.register('external_launch', callable=self.got_external_launch)
    try:
      self.app_mgr.connect()
      self.app_mgr.external_launch(list(sys.argv[1:]))
      logging.info("App already running. Sending: {}".format(sys.argv[1:]))
      exit()
    except ConnectionRefusedError: #App isn't running yet
      ""

  def run(self):
    self.app_mgr.get_server().serve_forever()

  def got_external_launch(self, args):
    logging.info("Got external launch: {}".format(args))
    if len(args) == 0:
      return
    value = args[0] if type(args) == list else args
    self.messaged.emit(value)


## Main app entry point
if __name__ == "__main__":
  launch_notifier = LaunchWorker()
  #If we make it this far, there is no other instance running
  thread = QThread()
  worker = LaunchWorker()
  worker.moveToThread(thread)
  thread.started.connect(worker.run)
  thread.start()
    
  #Settings need to be loaded seperately
  AppInstance.settings = AppSettings()
  first_launch = AppInstance.settings.on_load()

  app = QApplication(sys.argv)

  if test_rpc_status(first_launch):
    AppInstance.on_init()
    #Finally init/run main window
    window = MainWindow()
    window.show()

    worker.messaged.connect(window.on_url_handled)
    logging.info("App Startup")

    error = None
    try:
      app.exec_()
    except (Exception) as e:
      error = e
    
    AppInstance.on_exit(error)
