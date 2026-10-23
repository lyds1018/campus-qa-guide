import axios, { type AxiosRequestConfig } from "axios";

export const http = axios.create({ baseURL: "/api", timeout: 10_000 });

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
