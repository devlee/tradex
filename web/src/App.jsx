import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ClockPage from "./pages/ClockPage";
import SecretaryPage from "./pages/SecretaryPage";
import Secretary2Page from "./pages/Secretary2Page";
import Secretary3Page from "./pages/Secretary3Page";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ClockPage />} />
        <Route path="secretary" element={<SecretaryPage />} />
        <Route path="secretary-2" element={<Secretary2Page />} />
        <Route path="secretary-3" element={<Secretary3Page />} />
      </Route>
    </Routes>
  );
}
