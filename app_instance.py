import os.path, logging
from logging.handlers import TimedRotatingFileHandler
from util import ensure_directory

LOG_STORAGE_PATH = "~/.raventrader/logs/raventrader.log"

class AppInstance:
  settings = None
  storage = None
  wallet = None
  server = None

  @staticmethod
  def setup_logging():
    path = os.path.expanduser(LOG_STORAGE_PATH)
    ensure_directory(os.path.dirname(path))
    logger = logging.getLogger()
    handler = TimedRotatingFileHandler(path, when='D', interval=1, backupCount=7)
    fmt = '%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s'
    formatter = logging.Formatter(fmt=fmt, datefmt='%m/%d/%Y %H:%M:%S')
    handler.setFormatter(formatter)
    handler.setLevel(logging.INFO)
    # tee output to console as well
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(logging.INFO)
    logger.addHandler(console)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

  @staticmethod
  def on_init():
    AppInstance.setup_logging()
    AppInstance.storage = AppStorage()
    AppInstance.wallet = WalletManager()
    AppInstance.server = ServerConnection()
    AppInstance.on_load()

  @staticmethod
  def on_load():
    AppInstance.storage.on_load()
    AppInstance.wallet.invalidate_all()
    AppInstance.wallet.on_load()
    #AppInstance.server.on_load()

  @staticmethod
  def on_close():
    AppInstance.wallet.on_close()
    AppInstance.storage.on_close()
    AppInstance.settings.on_close()

  @staticmethod
  def on_exit(error=None):
    if error:
      logging.error(error)
    AppInstance.on_close()


from app_storage import AppStorage
from wallet_manager import WalletManager
from server_connection import ServerConnection