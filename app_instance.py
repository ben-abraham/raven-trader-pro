class AppInstance:
  settings = None
  storage = None
  wallet = None
  server = None

  @staticmethod
  def on_init():
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
      print("App Error: ", error)
    AppInstance.on_close()


from app_storage import AppStorage
from wallet_manager import WalletManager
from server_connection import ServerConnection