import random

def ohlcv_stream(start=100.0, volatility=2.0, n_ticks=200):
    price = start
    for _ in range(n_ticks):
        o = price + random.uniform(-volatility, volatility)
        h = o + abs(random.uniform(0, volatility*1.5))
        l = o - abs(random.uniform(0, volatility*1.5))
        c = l + random.random() * (h - l)
        v = random.randint(100, 1000)
        price = c
        yield {'open': round(o,2), 'high': round(h,2), 'low': round(l,2), 'close': round(c,2), 'volume': v}

class Trade:
    def __init__(self, entry, qty, entry_price, sl=None):
        self.entry = entry
        self.qty = qty
        self.entry_price = entry_price
        self.sl = sl
        self.active = True
        self.exit = None
        self.exit_price = None
        self.profit = None

    def try_exit(self, price, tick):
        if not self.active:
            return False
        sl_triggered = self.sl and price <= self.sl and self.qty > 0
        if sl_triggered:
            self.active = False
            self.exit = tick
            self.exit_price = self.sl
            self.profit = (self.sl - self.entry_price) * self.qty
            return True
        return False

    def close(self, price, tick):
        if self.active:
            self.active = False
            self.exit = tick
            self.exit_price = price
            self.profit = (price - self.entry_price) * self.qty

class AdvancedSimulator:
    def __init__(self, cash=10000, risk_per_trade=0.02, max_trades=3, sl_pct=0.03,
                 short_window=7, long_window=21, rsi_period=14, vol_window=10, breakout_pct=1.5):
        self.init_cash = self.cash = cash
        self.equity_curve = []
        self.prices = []
        self.closes = []
        self.trades = []
        self.position = 0
        self.max_trades = max_trades
        self.risk_per_trade = risk_per_trade
        self.sl_pct = sl_pct
        self.short_window = short_window
        self.long_window = long_window
        self.rsi_period = rsi_period
        self.vol_window = vol_window
        self.breakout_pct = breakout_pct
        self.active_trades = []
        self.trade_log = []

    def moving_average(self, closes, window):
        if len(closes) < window:
            return None
        return sum(closes[-window:]) / window

    def compute_rsi(self, closes):
        if len(closes) < self.rsi_period + 1:
            return None
        gains = [max(0, closes[i] - closes[i-1]) for i in range(-self.rsi_period, 0)]
        losses = [max(0, closes[i-1] - closes[i]) for i in range(-self.rsi_period, 0)]
        avg_gain = sum(gains)/self.rsi_period
        avg_loss = sum(losses)/self.rsi_period
        if avg_loss == 0:
            return 100
        rs = avg_gain/avg_loss
        return 100 - (100/(1+rs))

    def compute_volatility(self, highs, lows):
        if len(highs) < self.vol_window:
            return None
        return sum([h - l for h, l in zip(highs[-self.vol_window:], lows[-self.vol_window:])]) / self.vol_window

    def on_tick(self, ohlcv, tickn):
        o, h, l, c, v = ohlcv['open'], ohlcv['high'], ohlcv['low'], ohlcv['close'], ohlcv['volume']
        self.prices.append(ohlcv)
        self.closes.append(c)
        highs = [p['high'] for p in self.prices]
        lows = [p['low'] for p in self.prices]

        eq = self.cash + sum([tr.qty*(c if tr.active else tr.exit_price) for tr in self.active_trades])
        self.equity_curve.append(eq)

        for tr in self.active_trades[:]:
            exited = tr.try_exit(l, tickn)
            if exited:
                self.trade_log.append((tickn, 'SL-EXIT', tr.entry_price, tr.exit_price, tr.qty, tr.profit))
                self.cash += tr.exit_price * tr.qty
                self.active_trades.remove(tr)

        short_ma = self.moving_average(self.closes, self.short_window)
        long_ma = self.moving_average(self.closes, self.long_window)
        rsi = self.compute_rsi(self.closes)
        vol = self.compute_volatility(highs, lows)
        typical_breakout = highs[-1] > max(highs[-self.vol_window:]) * (1 + self.breakout_pct/100) if len(highs) > self.vol_window else False

        can_enter = len(self.active_trades) < self.max_trades and self.cash > 0
        price = c

        buy_signal = (
            short_ma is not None and long_ma is not None and rsi is not None and vol is not None
            and short_ma > long_ma and rsi < 70 and typical_breakout
        )

        if buy_signal and can_enter:
            risk_amt = self.init_cash * self.risk_per_trade
            qty = int(risk_amt / (price * self.sl_pct)) or 1
            if qty * price > self.cash:
                qty = int(self.cash // price)
            if qty > 0:
                stop = price * (1 - self.sl_pct)
                trade = Trade(entry=tickn, qty=qty, entry_price=price, sl=stop)
                self.cash -= qty*price
                self.active_trades.append(trade)
                self.trade_log.append((tickn, 'ENTRY', price, None, qty, None))
                print(f"ENTRY at {price:.2f}, qty={qty}, stop={stop:.2f}, RSI={rsi:.1f}, Vol={vol:.2f}")

        for tr in self.active_trades[:]:
            exit_signal = (short_ma is not None and long_ma is not None and short_ma < long_ma) or (rsi is not None and rsi > 75)
            if tr.active and exit_signal:
                tr.close(price, tickn)
                self.cash += price*tr.qty
                self.trade_log.append((tickn, 'MANUAL-EXIT', tr.entry_price, price, tr.qty, tr.profit))
                self.active_trades.remove(tr)
                print(f"MANUAL-EXIT at {price:.2f}, profit={tr.profit:.2f}")

    def statistics(self):
        print("\n==== TRADE LOG ====")
        for log in self.trade_log:
            print(log)
        all_profits = [t[5] for t in self.trade_log if t[1] != 'ENTRY' and t[5] is not None]
        eq = self.cash + sum([tr.qty*(self.closes[-1] if tr.active else tr.exit_price) for tr in self.active_trades])
        peak = max(self.equity_curve) if self.equity_curve else self.init_cash
        trough = min(self.equity_curve) if self.equity_curve else self.init_cash
        dd = peak - trough
        wins = sum(1 for p in all_profits if p > 0)
        losses = sum(1 for p in all_profits if p <= 0)
        print("\n==== STATISTICS ====")
        print(f"Ending equity: {eq:.2f}")
        print(f"Total P/L: {sum(all_profits):.2f}")
        print(f"Trades closed: {len(all_profits)}")
        print(f"Win rate: {(100*wins/(wins+losses)):.1f}%" if wins+losses > 0 else "-")
        print(f"Max Drawdown: {dd:.2f}")
        print(f"Trades active: {len([t for t in self.active_trades if t.active])}")

sim = AdvancedSimulator()
for i, tick in enumerate(ohlcv_stream()):
    sim.on_tick(tick, i)

sim.statistics()
