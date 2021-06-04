from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, json, time, getpass, os.path
from util import *
from rvn_rpc import *

from app_settings import AppSettings

SERVER_TYPE_BUY = 0
SERVER_TYPE_SELL = 1
SERVER_TYPE_TRADE = 2

class ServerConnection:

  def __init__ (self):
    super()

  def get_url(self, subpath):
    base_url = AppSettings.instance.read("server_url")
    if not base_url:
      return None
    return "{}/{}".format(base_url, subpath)

  def exec_url(self, method, url, **kwargs):
    req = dict(kwargs)
    try:
      resp = get(url, params=req) if method == "GET" else post(url, json=req)
      if resp.status_code != 200:
        print("RTServer ==> {} {} {}".format(method, url, req))
        print("RTServer <== {}".format(resp.text))
      j_resp = json.loads(resp.text)
      if "error" in j_resp and j_resp["error"]:
        print("RT Error: ", j_resp["error"])
        return None
      else:
        return j_resp
    except:
      print("RT Server Error")
      return None

  def do_get(self, url, **kwargs):
    return self.exec_url("GET", url, **kwargs)

  def do_post(self, url, **kwargs):
    return self.exec_url("POST", url, **kwargs)

  def search_listings(self, asset_name=None, swap_type=None, offset=None, page_size=None):
    url = self.get_url("api/sitedata/listings")
    return self.do_get(url, assetName=asset_name, swapType=swap_type, pageSize=page_size, offset=offset)

  def test_swap(self, swap):
    url = self.get_url("api/assets/quickparse")
    return self.do_post(url, Hex=swap.raw)

  def post_swap(self, swap):
    url = self.get_url("api/assets/list")
    result = self.do_post(url, Hex=swap.raw)
    if result["valid"]:
      return (True, result)
    else:
      return (False, result["error"])