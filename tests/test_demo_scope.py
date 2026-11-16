from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from backend.demo_scope import classify_contract,expand_flat_scope
from backend.executor import Halt
from backend.strategy_v2 import StrategyEngine,StrategyPolicy
from tests.test_strategy_v2 import DemoFake,signal,D


def contract(symbol,kind='COIN',**extra):
    return dict(symbol=symbol,status='TRADING',quoteAsset='USDT',marginAsset='USDT',
        contractType='PERPETUAL',orderTypes=['LIMIT','MARKET','STOP_MARKET'],
        timeInForce=['IOC'],underlyingType=kind,underlyingSubType=[],**extra)


class DemoScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name)/'state.db'
        self.policy=StrategyPolicy('60','0.40',10,3,'0.03','60','initial_net_loss',60,{'BTCUSDT':'crypto'})
        self.policy_path=self.data.parent/'demo-policy.json';self.policy_path.write_text(json.dumps(self.policy.public()))
        self.broker=DemoFake()
        self.broker.catalogue=Mock(return_value={'symbols':[contract('BTCUSDT'),contract('ETHUSDT'),
            contract('NVDAUSDT','EQUITY'),contract('XAUUSDT','COMMODITY'),contract('UNKNOWNUSDT','PREMARKET')]})
        self.broker.all_open_orders=Mock(return_value=[]);self.broker.all_open_stops=Mock(return_value=[])
    def tearDown(self):self.temp.cleanup()
    def test_classification_requires_supported_contract_and_explicit_category(self):
        self.assertEqual(classify_contract(contract('ETHUSDT')),'crypto')
        self.assertEqual(classify_contract(contract('NVDAUSDT','EQUITY')),'equity')
        self.assertEqual(classify_contract(contract('XAUUSDT','COMMODITY')),'traditional')
        self.assertIsNone(classify_contract(contract('UNKNOWNUSDT','PREMARKET')))
        row=contract('PREIPOUSDT','PREMARKET');row['underlyingSubType']=['TradFi','Pre-IPO']
        self.assertEqual(classify_contract(row),'equity')
        for field,value in [('status','SETTLING'),('marginAsset','USDC'),('contractType','CURRENT_QUARTER')]:
            row=contract('BTCUSDT');row[field]=value;self.assertIsNone(classify_contract(row))
    def test_scope_expansion_preserves_verified_capital_history_and_loss_basis(self):
        path=self.data.parent/'demo-execution.sqlite3';engine=StrategyEngine(path,self.policy,self.broker)
        engine.handle(signal('old-open'));engine.handle(signal('old-close','CLOSE_LONG'))
        before=engine.book.public();engine.close()
        result=expand_flat_scope(self.data,self.broker)
        new=StrategyPolicy(**json.loads(self.policy_path.read_text()))
        self.assertEqual(new.symbols,{'BTCUSDT':'crypto','ETHUSDT':'crypto','NVDAUSDT':'equity','XAUUSDT':'traditional'})
        self.assertEqual(new.initial_capital,'60');self.assertEqual(new.max_loss,'60')
        engine=StrategyEngine(path,new,self.broker)
        self.assertEqual(engine.book.public(),before);engine.close()
        self.assertTrue(result['history_preserved']);self.assertTrue(result['prepare_demo_leverage'])
        self.assertEqual(len(list((self.data.parent/'scope-backups').glob('*.sqlite3'))),1)
    def test_active_manual_position_blocks_expansion_without_editing_policy(self):
        original=self.policy_path.read_text();self.broker.positions[('BTCUSDT','LONG')]=(D('1'),D('100'))
        with self.assertRaises(Halt):expand_flat_scope(self.data,self.broker)
        self.assertEqual(self.policy_path.read_text(),original)
    def test_failed_policy_file_update_rolls_back_journal_fingerprint(self):
        original_replace=Path.replace
        def fail_policy(path,target):
            if path.name=='demo-policy.scope.tmp':raise OSError('injected policy write failure')
            return original_replace(path,target)
        with patch.object(Path,'replace',new=fail_policy):
            with self.assertRaises(OSError):expand_flat_scope(self.data,self.broker)
        engine=StrategyEngine(self.data.parent/'demo-execution.sqlite3',self.policy,self.broker)
        self.assertEqual(engine.book.capital(),D('60'));engine.close()
    def test_production_transport_is_never_allowed(self):
        self.broker.environment='production'
        with self.assertRaises(Halt):expand_flat_scope(self.data,self.broker)


class DemoLazyLeverageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.broker=DemoFake()
        self.policy=StrategyPolicy('60','0.40',10,3,'0.03','60','initial_net_loss',60,
                                   {'BTCUSDT':'crypto','ETHUSDT':'crypto','NVDAUSDT':'equity'})
        self.settings={'BTCUSDT':10,'ETHUSDT':20,'NVDAUSDT':20}
        self.broker.symbol_config=Mock(side_effect=lambda s:{'leverage':self.settings[s]})
        self.broker.symbol_class=Mock(side_effect=lambda s:self.policy.symbols[s])
        self.broker.prepare_leverage=Mock(side_effect=lambda s,n:self.settings.update({s:n}))
        self.engine=StrategyEngine(Path(self.temp.name)/'journal.db',self.policy,self.broker,prepare_demo_leverage=True)
    def tearDown(self):self.engine.close();self.temp.cleanup()
    def test_new_crypto_symbol_prepares_ten_x_before_its_first_entry(self):
        self.engine.handle(signal('eth','OPEN_LONG','ETHUSDT'))
        self.broker.prepare_leverage.assert_called_once_with('ETHUSDT',10)
        self.assertEqual(self.engine.book.positions()[0]['leverage'],10)
    def test_equity_prepares_three_x(self):
        self.engine.handle(signal('stock','OPEN_LONG','NVDAUSDT'))
        self.broker.prepare_leverage.assert_called_once_with('NVDAUSDT',3)
        self.assertEqual(self.engine.book.positions()[0]['leverage'],3)
    def test_existing_pool_prevents_another_entry_and_leverage_change(self):
        self.engine.handle(signal('btc'))
        result=self.engine.handle(signal('eth','OPEN_LONG','ETHUSDT'))
        self.assertEqual(result['reason'],'allocated_pool_in_use')
        self.broker.prepare_leverage.assert_not_called();self.assertEqual(self.broker.submit_count,1)
    def test_changed_classification_is_skipped_before_leverage_or_orders(self):
        self.broker.symbol_class.return_value=None;self.broker.symbol_class.side_effect=None
        result=self.engine.handle(signal('changed','OPEN_LONG','ETHUSDT'))
        self.assertEqual(result['reason'],'symbol_not_tradeable_or_class_changed')
        self.broker.prepare_leverage.assert_not_called();self.assertEqual(self.broker.submit_count,0)
    def test_unconfirmed_leverage_never_opens_a_position(self):
        self.broker.prepare_leverage.side_effect=None
        with self.assertRaisesRegex(Halt,'read back'):self.engine.handle(signal('unconfirmed','OPEN_LONG','ETHUSDT'))
        self.assertEqual(self.broker.submit_count,0)
