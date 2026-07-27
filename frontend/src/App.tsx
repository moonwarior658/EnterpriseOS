import { Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from './components/ProtectedRoute'
import AppLayout from './layouts/AppLayout'
import AutomationSchedulesPage from './pages/AutomationSchedulesPage'
import AutomationDiagnosticsPage from './pages/AutomationDiagnosticsPage'
import DashboardPage from './pages/DashboardPage'
import LoginPage from './pages/LoginPage'
import PublicSupplyRequestPage from './pages/PublicSupplyRequestPage'
import SupplyRequestDetailPage from './pages/SupplyRequestDetailPage'
import SupplyRequestListPage from './pages/SupplyRequestListPage'
import SupplyDebtListPage from './pages/SupplyDebtListPage'
import UsersPage from './pages/UsersPage'
import WorkRequestDetailPage from './pages/WorkRequestDetailPage'
import WorkRequestFormPage from './pages/WorkRequestFormPage'
import WorkRequestListPage from './pages/WorkRequestListPage'
import './App.css'

function App() {
  return (
    <Routes>
      <Route
        path="/login"
        element={<LoginPage />}
      />
      <Route
        path="/public/requests/warehouse"
        element={<WorkRequestFormPage requestType="warehouse" />}
      />
      <Route
        path="/public/requests/repair"
        element={<WorkRequestFormPage requestType="repair" />}
      />
      <Route
        path="/request/warehouse"
        element={<Navigate to="/public/requests/warehouse" replace />}
      />
      <Route
        path="/request/repair"
        element={<Navigate to="/public/requests/repair" replace />}
      />
      <Route
        path="/request/supply"
        element={<PublicSupplyRequestPage />}
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
          path="/requests/warehouse/new"
          element={<Navigate to="/public/requests/warehouse" replace />}
        />

        <Route
          path="/requests/repair/new"
          element={<Navigate to="/public/requests/repair" replace />}
        />

        <Route
          path="/requests/warehouse"
          element={<WorkRequestListPage requestType="warehouse" />}
        />

        <Route
          path="/requests/repair"
          element={<WorkRequestListPage requestType="repair" />}
        />

        <Route
          path="/requests/:requestId"
          element={<WorkRequestDetailPage />}
        />

        <Route
          path="/supply/requests"
          element={<ProtectedRoute adminOnly><SupplyRequestListPage /></ProtectedRoute>}
        />

        <Route
          path="/supply/requests/:requestId"
          element={<ProtectedRoute adminOnly><SupplyRequestDetailPage /></ProtectedRoute>}
        />

        <Route
          path="/supply/debts"
          element={<ProtectedRoute adminOnly><SupplyDebtListPage /></ProtectedRoute>}
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
