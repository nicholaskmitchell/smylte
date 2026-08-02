import { useEffect, useRef, useState } from 'react'
import { api, type List, type Task } from './api'
import { makeGuard } from './util'

// Keep in sync with the mobile breakpoint in styles/app.css.
const MOBILE_QUERY = '(max-width: 720px)'

export function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(() => window.matchMedia(MOBILE_QUERY).matches)
  useEffect(() => {
    const mq = window.matchMedia(MOBILE_QUERY)
    const onChange = (e: MediaQueryListEvent) => setMobile(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return mobile
}

/**
 * Every task on the account, refetched whenever `rev` changes.
 *
 * Read-only on purpose. TasksView keeps its own copy of this fan-out because
 * that one also has to survive optimistic writes — its fetch token is bumped by
 * mutations so a refetch whose snapshot predates a local paint gets dropped.
 * The dashboard has no writes to protect, so it only needs the ordering half of
 * that contract: a response commits only while its token is still the newest,
 * which is what stops a slow first load from clobbering a fast SSE-driven one.
 */
export function useAllTasks(rev: number, onExpire: () => void) {
  const [lists, setLists] = useState<List[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const token = useRef(0)
  const expire = useRef(onExpire)
  expire.current = onExpire

  useEffect(() => {
    const mine = ++token.current
    makeGuard(() => expire.current())(async () => {
      const ls = await api.lists()
      if (mine !== token.current) return
      setLists(ls)
      const ts = (await Promise.all(ls.map((l) => api.tasks(l.id)))).flat()
      if (mine !== token.current) return
      setTasks(ts)
      setLoading(false)
    })
  }, [rev])

  return { lists, tasks, loading }
}
