import { Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from './components/ProtectedRoute'
import AppLayout from './layouts/AppLayout'
import AutomationSchedulesPage from './pages/AutomationSchedulesPage'
import AutomationDiagnosticsPage from './pages/AutomationDiagnosticsPage'
import DashboardPage from './pages/DashboardPage'
import LoginPage from './pages/LoginPage'
import UsersPage from './pages/UsersPage'
import './App.css'

function App() {
  return (
    <Routes>
      <Route
        path="/login"
        element={<LoginPage />}
      />

      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route
          path="/dashboard"
          element={<DashboardPage />}
        />

        <Route
          path="/users"
          element={
            <ProtectedRoute adminOnly>
              <UsersPage />
            </ProtectedRoute>
          }
        />

        <Route
          path="/automation/diagnostics"
          element={
            <ProtectedRoute adminOnly>
              <AutomationDiagnosticsPage />
            </ProtectedRoute>
          }
        />

        <Route
          path="/automation/schedules"
          element={
            <ProtectedRoute adminOnly>
              <AutomationSchedulesPage />
            </ProtectedRoute>
          }
        />
      </Route>

      <Route
        path="/"
        element={<Navigate to="/dashboard" replace />}
      />

      <Route
        path="*"
        element={<Navigate to="/dashboard" replace />}
      />
    </Routes>
  )
}

export default App
