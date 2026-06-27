"use client"
import { useState, useEffect, useCallback } from "react"
import { DEFAULT_PAGE_SIZE } from "@/lib/constants"

export function usePagination(dependencies: unknown[] = []) {
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [total, setTotal] = useState(0)

  // Reset page when filters/size change
  useEffect(() => {
    setPage(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependencies, pageSize])

  const handlePageSizeChange = useCallback((size: number) => {
    setPageSize(size)
    setPage(0)
  }, [])

  return { page, setPage, pageSize, handlePageSizeChange, total, setTotal, offset: page * pageSize }
}
