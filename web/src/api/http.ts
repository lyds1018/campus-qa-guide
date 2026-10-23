import axios, { type AxiosRequestConfig } from "axios";

/**
 * 演示 token：P5 不做真登录，两枚固定 token 换身份。
 * 换真登录时只改这里（改成从 cookie / OIDC 回调取）。
 */
const TOKEN_KEY = "campus-demo-token";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "student-demo";
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export const http = axios.create({ baseURL: "/api", timeout: 30_000 });

http.interceptors.request.use((config) => {
  config.headers = config.headers ?? {};
  config.headers["X-Demo-Token"] = getToken();
  return config;
});

export interface ApiError {
  status: number;
  detail: string;
  /** 原始响应体，503 降级时用来取 checks 明细 */
  data?: unknown;
}

http.interceptors.response.use(
  (r) => r.data,
  (e) =>
    Promise.reject({
      status: e.response?.status ?? 0,
      detail: e.response?.data?.detail ?? "网络异常",
      data: e.response?.data,
    } satisfies ApiError),
);

/** 响应拦截器已解包 data，这里返回的直接是业务体 */
export function get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return http.get(url, config) as unknown as Promise<T>;
}

export function post<T>(url: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return http.post(url, body, config) as unknown as Promise<T>;
}

export function put<T>(url: string, body?: unknown): Promise<T> {
  return http.put(url, body) as unknown as Promise<T>;
}

export function del<T>(url: string): Promise<T> {
  return http.delete(url) as unknown as Promise<T>;
}
