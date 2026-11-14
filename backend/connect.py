"""Collect credentials locally in memory and launch the same local dashboard."""
import getpass
import os
import argparse


def main(argv=None):
    parser=argparse.ArgumentParser(description='Local account credential entry')
    parser.add_argument('--production-read-only',action='store_true',help='Use production and disable account order execution')
    args,server_args=parser.parse_known_args(argv)
    print('Polo CopyTrade — local account connection / 本机账户连接')
    print('Keys remain in this process. They are not saved to source files or sent to chat.')
    if args.production_read_only:
        choice='1'
        server_args.append('--read-only-account')
        print('PRODUCTION / READ-ONLY: account orders are disabled in this session.')
    else:
        choice=input('Environment: 1 = production 真实账户, 2 = Binance testnet 测试网 [2]: ').strip() or '2'
    if choice not in ('1','2'):raise SystemExit('Invalid environment')
    os.environ['POLO_BINANCE_ENV']='production' if choice=='1' else 'testnet'
    os.environ['POLO_BINANCE_API_KEY']=getpass.getpass('API Key (hidden / 输入隐藏): ').strip()
    os.environ['POLO_BINANCE_API_SECRET']=getpass.getpass('API Secret (hidden / 输入隐藏): ').strip()
    if not os.environ['POLO_BINANCE_API_KEY'] or not os.environ['POLO_BINANCE_API_SECRET']:
        raise SystemExit('Both values are required')
    print('Opening the server does not place orders. Connect, inspect, configure and explicitly start in the dashboard.')
    from .server import main as server_main
    server_main(server_args)


if __name__=='__main__':main()
