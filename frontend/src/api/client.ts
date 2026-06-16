import axios from "axios"

const client = axios.create({
  baseURL: "/api/v1",
  timeout: 360000, // 6 min — unified timeout across full chain
  headers: {
    "Content-Type": "application/json",
  },
})

// Standardize error messages so upstream handlers (React Query global onError) get clean text
client.interceptors.response.use(
  (response) => response,
  (error) => {
    // No response at all → network error
    if (!error.response) {
      error.message = "网络连接失败，请检查网络"
      return Promise.reject(error)
    }

    const { status, data } = error.response

    // 409 MARKET_CLOSED — extract backend message (toast handled globally)
    if (status === 409 && data?.detail?.code === "MARKET_CLOSED") {
      error.message = data.detail.message || "当前非交易时段，无法执行交易"
      return Promise.reject(error)
    }

    // Timeout variants
    if (status === 408 || status === 504) {
      error.message = "请求超时，请稍后重试"
      return Promise.reject(error)
    }

    // Server errors
    if (status >= 500) {
      error.message = "服务器异常，请稍后重试"
      return Promise.reject(error)
    }

    // Structured error from backend
    if (data?.detail && typeof data.detail === "string") {
      error.message = data.detail
    } else if (data?.message) {
      error.message = data.message
    }

    return Promise.reject(error)
  },
)

export default client
