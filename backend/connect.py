"""Collect credentials locally in memory and launch the same local dashboard."""
import getpass
import os


def main(argv=None):
    print('Polo CopyTrade — local account connection / 本机账户连接')
    print('Keys remain in this process. They are not saved to source files or sent to chat.')
    choice=input('Environment: 1 = production 真实账户, 2 = Binance testnet 测试网 [2]: ').strip() or '2'
    if choice not in ('1','2'):raise SystemExit('Invalid environment')
    os.environ['POLO_BINANCE_ENV']='production' if choice=='1' else 'testnet'
    os.environ['POLO_BINANCE_API_KEY']=getpass.getpass('API Key (hidden / 输入隐藏): ').strip()
    os.environ['POLO_BINANCE_API_SECRET']=getpass.getpass('API Secret (hidden / 输入隐藏): ').strip()
    if not os.environ['POLO_BINANCE_API_KEY'] or not os.environ['POLO_BINANCE_API_SECRET']:
        raise SystemExit('Both values are required')
    print('Opening the server does not place orders. Connect, inspect, configure and explicitly start in the dashboard.')
    from .server import main as server_main
    server_main(argv)


if __name__=='__main__':main()
