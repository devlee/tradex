import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ClockPage from "./pages/ClockPage";
import SecretaryPage from "./pages/SecretaryPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ClockPage />} />
        <Route path="secretary" element={<SecretaryPage />} />
      </Route>
    </Routes>
  );
}
