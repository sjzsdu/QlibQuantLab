"use client";

/**
 * TanStack Query 的统一封装：
 * - useApiQuery   —— GET 查询（走 lib/api.ts，自动带 cookie / 解信封 / 401 跳转）
 * - useApiMutation —— 写操作（POST/PATCH/PUT/DELETE，自动附加 X-CSRF-Token）
 */

import {
  useMutation,
  useQuery,
  type QueryKey,
  type UseMutationOptions,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { apiFetch, type ApiError, type HttpMethod } from "@/lib/api";

export type ApiQueryOptions<T> = Omit<
  UseQueryOptions<T, ApiError, T, QueryKey>,
  "queryKey" | "queryFn"
>;

/** GET 查询：queryKey 由调用方给出，path 为 /api 之后的相对路径（如 /v1/projects） */
export function useApiQuery<T>(
  queryKey: QueryKey,
  path: string,
  options?: ApiQueryOptions<T>,
) {
  return useQuery<T, ApiError, T, QueryKey>({
    queryKey,
    queryFn: () => apiFetch<T>(path),
    ...options,
  });
}

export interface ApiMutationInput {
  /** /api 之后的相对路径（如 /v1/projects） */
  path: string;
  /** 默认 POST */
  method?: Exclude<HttpMethod, "GET">;
  /** 请求体（自动 JSON 序列化；DELETE 通常不传） */
  body?: unknown;
}

export type ApiMutationOptions<TData, TInput> = Omit<
  UseMutationOptions<TData, ApiError, TInput>,
  "mutationFn"
>;

/** 写操作；成功后调用方自行 invalidateQueries 刷新列表 */
export function useApiMutation<
  TData,
  TInput extends ApiMutationInput = ApiMutationInput,
>(options?: ApiMutationOptions<TData, TInput>) {
  return useMutation<TData, ApiError, TInput>({
    mutationFn: (input) =>
      apiFetch<TData>(input.path, {
        method: input.method ?? "POST",
        body:
          input.body === undefined ? undefined : JSON.stringify(input.body),
      }),
    ...options,
  });
}
