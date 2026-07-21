import { BrowserRouter, Routes, Route } from 'react-router-dom';
import AdversaryApp from './pages/AdversaryApp';
import { LandingPage } from './pages/LandingPage';
import { AuthProvider } from './AuthContext';
import { LoginPage } from './pages/LoginPage';
import { OAuthCallback } from './pages/OAuthCallback';

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/auth/callback" element={<OAuthCallback />} />
          <Route path="/app" element={<AdversaryApp />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
