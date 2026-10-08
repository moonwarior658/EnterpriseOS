import { Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from './components/ProtectedRoute'
import AppLayout from './layouts/AppLayout'
import AutomationSchedulesPage from './pages/AutomationSchedulesPage'
import AutomationDiagnosticsPage from './pages/AutomationDiagnosticsPage'
import DashboardPage from './pages/DashboardPage'
import LoginPage from './pages/LoginPage'
import IikoMappingPage from './pages/IikoMappingPage'
import SupplyRequestDetailPage from './pages/SupplyRequestDetailPage'
import SupplyRequestCreatePage from './pages/SupplyRequestCreatePage'
import SupplyRequestListPage from './pages/SupplyRequestListPage'
import SupplyDebtListPage from './pages/SupplyDebtListPage'
import SupplySuppliersPage from './pages/SupplySuppliersPage'
import SupplyPurchaseRequestsPage from './pages/SupplyPurchaseRequestsPage'
import SupplyPurchaseRequestDetailPage from './pages/SupplyPurchaseRequestDetailPage'
import SupplyProductionProcurementPage from './pages/SupplyProductionProcurementPage'
import SupplySupplierOrdersPage from './pages/SupplySupplierOrdersPage'
import SupplySupplierOrderDetailPage from './pages/SupplySupplierOrderDetailPage'
import SupplySupplierPaymentsPage from './pages/SupplySupplierPaymentsPage'
import UsersPage from './pages/UsersPage'
import EmployeesPage from './pages/EmployeesPage'
import EmployeeDetailPage from './pages/EmployeeDetailPage'
import AuditPage from './pages/AuditPage'
import WorkRequestDetailPage from './pages/WorkRequestDetailPage'
import WorkRequestFormPage from './pages/WorkRequestFormPage'
import WorkRequestListPage from './pages/WorkRequestListPage'
import RepairContractorsPage from './pages/RepairContractorsPage'
import StatisticsPage from './pages/StatisticsPage'
import { SALES_ROLES } from './pages/salesAnalyticsLogic'
import type { EmployeeRole } from './services/actionContext'
import ProductKnowledgePage from './pages/ProductKnowledgePage'
import { PRODUCT_KNOWLEDGE_ROLES } from './services/productKnowledge'
import ProductKnowledgeDemoPage from './pages/ProductKnowledgeDemoPage'
import ProductKnowledgeDemoLayout from './pages/ProductKnowledgeDemoLayout'
import './App.css'

function App() {
  return (
    <Routes>
      {import.meta.env.DEV && <Route element={<ProductKnowledgeDemoLayout />}>
        <Route path="/dev/products" element={<ProductKnowledgeDemoPage basePath="/dev/products" />} />
        <Route path="/dev/products/:productId" element={<ProductKnowledgeDemoPage basePath="/dev/products" />} />
      </Route>}
      <Route
        path="/login"
        element={<LoginPage />}
      />
      <Route
        path="/public/requests/repair"
        element={<Navigate to="/requests/repair/new" replace />}
      />
      <Route
        path="/request/warehouse"
        element={<Navigate to="/supply/requests" replace />}
      />
      <Route
        path="/request/repair"
        element={<Navigate to="/public/requests/repair" replace />}
      />
      <Route
        path="/request/supply"
        element={<Navigate to="/supply/requests" replace />}
      />

      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/products" element={<ProtectedRoute allowedRoles={PRODUCT_KNOWLEDGE_ROLES}><ProductKnowledgePage /></ProtectedRoute>} />
        <Route path="/products/:productId" element={<ProtectedRoute allowedRoles={PRODUCT_KNOWLEDGE_ROLES}><ProductKnowledgePage /></ProtectedRoute>} />
        <Route path="/statistics" element={<ProtectedRoute allowedRoles={SALES_ROLES as EmployeeRole[]}><StatisticsPage /></ProtectedRoute>} />
        <Route path="/statistics/:view" element={<ProtectedRoute allowedRoles={SALES_ROLES as EmployeeRole[]}><StatisticsPage /></ProtectedRoute>} />

        <Route
          path="/dashboard"
          element={<DashboardPage />}
        />

        <Route
          path="/requests/repair/new"
          element={<ProtectedRoute allowedRoles={['ADMIN', 'DEPUTY_DIRECTOR', 'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER', 'SELLER', 'DRIVER', 'CONFECTIONER', 'BAKER', 'HANDYMAN']}><WorkRequestFormPage /></ProtectedRoute>}
        />

        <Route
          path="/requests/repair"
          element={<ProtectedRoute allowedRoles={['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'ACCOUNTANT', 'SUPPLY_MANAGER', 'HANDYMAN', 'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER', 'SELLER', 'DRIVER', 'CONFECTIONER', 'BAKER']}><WorkRequestListPage /></ProtectedRoute>}
        />

        <Route path="/repairs/contractors" element={<ProtectedRoute allowedRoles={['ADMIN', 'SUPPLY_MANAGER']}><RepairContractorsPage /></ProtectedRoute>} />

        <Route
          path="/requests/:requestId"
          element={<ProtectedRoute allowedRoles={['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'ACCOUNTANT', 'SUPPLY_MANAGER', 'HANDYMAN', 'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER', 'SELLER', 'DRIVER', 'CONFECTIONER', 'BAKER']}><WorkRequestDetailPage /></ProtectedRoute>}
        />

        <Route
          path="/supply/requests"
          element={<ProtectedRoute allowedRoles={['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER', 'SELLER', 'SUPPLY_MANAGER', 'ACCOUNTANT']}><SupplyRequestListPage /></ProtectedRoute>}
        />
        <Route path="/supply/requests/new" element={<ProtectedRoute allowedRoles={['ADMIN', 'SUPPLY_MANAGER', 'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER', 'SELLER']}><SupplyRequestCreatePage /></ProtectedRoute>} />

        <Route
          path="/supply/requests/:requestId"
          element={<ProtectedRoute allowedRoles={['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER', 'SELLER', 'SUPPLY_MANAGER', 'ACCOUNTANT']}><SupplyRequestDetailPage /></ProtectedRoute>}
        />

        <Route
          path="/supply/debts"
          element={<ProtectedRoute allowedRoles={['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'SUPPLY_MANAGER', 'ACCOUNTANT']}><SupplyDebtListPage /></ProtectedRoute>}
        />

        <Route
          path="/supply/suppliers"
          element={<ProtectedRoute allowedRoles={['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'SUPPLY_MANAGER', 'ACCOUNTANT']}><SupplySuppliersPage /></ProtectedRoute>}
        />

        <Route
          path="/supply/purchase-requests"
          element={<ProtectedRoute allowedRoles={['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'SUPPLY_MANAGER', 'ACCOUNTANT']}><SupplyPurchaseRequestsPage /></ProtectedRoute>}
        />
        <Route path="/supply/production-procurement" element={<ProtectedRoute allowedRoles={['HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER']}><SupplyProductionProcurementPage /></ProtectedRoute>} />

        <Route
          path="/supply/purchase-requests/:requestId"
          element={<ProtectedRoute allowedRoles={['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'SUPPLY_MANAGER', 'ACCOUNTANT']}><SupplyPurchaseRequestDetailPage /></ProtectedRoute>}
        />

        <Route path="/supply/supplier-orders" element={<ProtectedRoute allowedRoles={['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'SUPPLY_MANAGER', 'ACCOUNTANT']}><SupplySupplierOrdersPage /></ProtectedRoute>} />
        <Route path="/supply/supplier-orders/:orderId" element={<ProtectedRoute allowedRoles={['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'SUPPLY_MANAGER', 'ACCOUNTANT']}><SupplySupplierOrderDetailPage /></ProtectedRoute>} />
        <Route path="/supply/supplier-payments" element={<ProtectedRoute allowedRoles={['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'SUPPLY_MANAGER', 'ACCOUNTANT']}><SupplySupplierPaymentsPage /></ProtectedRoute>} />

        <Route
          path="/integrations/iiko/mappings"
          element={<ProtectedRoute adminOnly><IikoMappingPage /></ProtectedRoute>}
        />

        <Route
          path="/users"
          element={
            <ProtectedRoute allowedRoles={['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'NETWORK_MANAGER']}>
              <UsersPage />
            </ProtectedRoute>
          }
        />

        <Route path="/employees" element={<ProtectedRoute allowBootstrap allowedRoles={['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION', 'SUPPLY_MANAGER']}><EmployeesPage /></ProtectedRoute>} />
        <Route path="/employees/:employeeId" element={<EmployeeDetailPage />} />
        <Route path="/audit" element={<ProtectedRoute allowedRoles={['ADMIN']}><AuditPage /></ProtectedRoute>} />

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
