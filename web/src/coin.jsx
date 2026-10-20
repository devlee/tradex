import { createContext, useContext, useState } from "react";

const CoinContext = createContext(null);

const COINS = ["NEAR", "PUMP", "HYPE"];

export function CoinProvider({ children }) {
  const [coin, setCoinState] = useState(() => {
    const saved = window.localStorage.getItem("tradex-coin");
    return COINS.includes(saved) ? saved : "NEAR";
  });

  function setCoin(next) {
    const value = COINS.includes(next) ? next : "NEAR";
    window.localStorage.setItem("tradex-coin", value);
    setCoinState(value);
  }

  return (
    <CoinContext.Provider value={{ coin, setCoin, coins: COINS }}>
      {children}
    </CoinContext.Provider>
  );
}

export function useCoin() {
  return useContext(CoinContext);
}

export function bookUrl(coin, file) {
  return coin === "NEAR" ? `/${file}` : `/${coin.toLowerCase()}/${file}`;
}
