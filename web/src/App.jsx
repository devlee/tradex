import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ClockPage from "./pages/ClockPage";
import StatsPage from "./pages/StatsPage";
import SecretaryPage from "./pages/SecretaryPage";
import Secretary2Page from "./pages/Secretary2Page";
import Secretary3Page from "./pages/Secretary3Page";
import Secretary4Page from "./pages/Secretary4Page";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<StatsPage />} />
        <Route path="clock" element={<ClockPage />} />
        <Route path="secretary" element={<SecretaryPage />} />
        <Route path="secretary-2" element={<Secretary2Page />} />
        <Route path="secretary-3" element={<Secretary3Page />} />
        <Route path="secretary-4" element={<Secretary4Page />} />
      </Route>
    </Routes>
  );
}
