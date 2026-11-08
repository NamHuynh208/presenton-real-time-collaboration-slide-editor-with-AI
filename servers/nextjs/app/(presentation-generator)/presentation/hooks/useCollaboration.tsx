'use client'
// Real-time co-editing: mirrors Redux `presentationData` into a shared Y.Doc
// (relay at /collab/<presentationId>, see collab/server.cjs) and applies other
// people's changes back into Redux. Auto-save keeps persisting the merged deck.
import { useEffect, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import * as Y from 'yjs';
import { WebsocketProvider } from 'y-websocket';
import { RootState } from '@/store/store';
import { setPresentationData, type PresentationData } from '@/store/slices/presentationGeneration';
import { diffMap, toY } from '@/lib/collab/yjs-json';

const LOCAL = 'presenton-local';
export type CollabPeer = { clientId: number; name: string; color: string };

const COLORS = ['#e11d48', '#2563eb', '#16a34a', '#d97706', '#7c3aed', '#0891b2'];

export function useCollaboration(enabled: boolean) {
  const dispatch = useDispatch();
  const { presentationData, isStreaming, isLoading } = useSelector(
    (state: RootState) => state.presentationGeneration
  );
  const latestRef = useRef<PresentationData | null>(presentationData);
  latestRef.current = presentationData;
  const docRef = useRef<Y.Doc | null>(null);
  const lastRef = useRef<Record<string, unknown> | null>(null);
  const syncedRef = useRef(false);
  const [peers, setPeers] = useState<CollabPeer[]>([]);

  const id = presentationData?.id;
  const ready = enabled && !!id && !isStreaming && !isLoading;

  useEffect(() => {
    if (!ready || !id) return;
    const doc = new Y.Doc();
    const deck = doc.getMap<unknown>('deck');
    const url = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/collab`;
    const provider = new WebsocketProvider(url, id, doc);
    docRef.current = doc;

    const applyRemote = () => {
      const data = deck.get('data');
      if (!(data instanceof Y.Map)) return;
      const json = data.toJSON() as Record<string, unknown>;
      lastRef.current = json;
      dispatch(setPresentationData({ ...(json as unknown as PresentationData), id }));
    };

    const onSync = (isSynced: boolean) => {
      if (!isSynced || syncedRef.current) return;
      syncedRef.current = true;
      const current = latestRef.current as unknown as Record<string, unknown> | null;
      if (!deck.has('data') && current) {
        // First editor in the room seeds it; concurrent seeds resolve to one winner.
        doc.transact(() => deck.set('data', toY(current)), LOCAL);
        lastRef.current = current;
      } else {
        applyRemote();
      }
    };
    provider.on('sync', onSync);
    deck.observeDeep((_events, tx) => {
      if (tx.origin === LOCAL || !syncedRef.current) return;
      applyRemote();
    });

    void fetch('/api/v1/auth/status', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => {
        const name = (s && s.username) || 'Guest';
        provider.awareness.setLocalStateField('user', { name, color: COLORS[doc.clientID % COLORS.length] });
      })
      .catch(() => undefined);
    const onAwareness = () => {
      const list: CollabPeer[] = [];
      provider.awareness.getStates().forEach((state, clientId) => {
        const user = (state as { user?: { name: string; color: string } }).user;
        if (user) list.push({ clientId, ...user });
      });
      setPeers(list);
    };
    provider.awareness.on('change', onAwareness);

    return () => {
      syncedRef.current = false;
      docRef.current = null;
      lastRef.current = null;
      provider.awareness.off('change', onAwareness);
      provider.destroy();
      doc.destroy();
      setPeers([]);
    };
  }, [ready, id, dispatch]);

  // Push local edits (anything that changed Redux) as minimal Yjs ops.
  useEffect(() => {
    const doc = docRef.current;
    if (!doc || !syncedRef.current || !presentationData || !lastRef.current) return;
    const data = doc.getMap<unknown>('deck').get('data');
    if (!(data instanceof Y.Map)) return;
    const next = presentationData as unknown as Record<string, unknown>;
    if (next === lastRef.current) return;
    doc.transact(() => diffMap(data, lastRef.current!, next), LOCAL);
    lastRef.current = next;
  }, [presentationData]);

  return { peers };
}
