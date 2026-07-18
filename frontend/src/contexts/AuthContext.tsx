import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'
import {
  getCurrentUser,
  getStoredToken,
  loginRequest,
  removeStoredToken,
  storeToken,
  type CurrentUser,
} from '../services/auth'

type AuthContextValue = {
  user: CurrentUser | null
  isLoading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const token = getStoredToken()

    if (!token) {
      setIsLoading(false)
      return
    }

    getCurrentUser(token)
      .then(setUser)
      .catch(() => {
        removeStoredToken()
        setUser(null)
      })
      .finally(() => {
        setIsLoading(false)
      })
  }, [])

  async function login(username: string, password: string) {
    const tokenResponse = await loginRequest(username, password)
    storeToken(tokenResponse.access_token)

    try {
      const currentUser = await getCurrentUser(
        tokenResponse.access_token,
      )
      setUser(currentUser)
    } catch (error) {
      removeStoredToken()
      throw error
    }
  }

  function logout() {
    removeStoredToken()
    setUser(null)
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)

  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider')
  }

  return context
}
