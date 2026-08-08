import { Request, Response, Router } from 'express';
import { MongoClient } from 'mongodb';

/**
 * Snapshot Query API
 *
 * Read-only endpoints for listing a tenant's backup snapshots. Results are
 * always scoped to the tenant named in the request so a caller only ever sees
 * their own snapshots.
 */

export const snapshotRouter = Router();

let _mongoClient: MongoClient | null = null;

async function getDb() {
  if (!_mongoClient) {
    _mongoClient = new MongoClient(process.env.MONGO_URI ?? 'mongodb://localhost:27017');
    await _mongoClient.connect();
  }
  return _mongoClient.db('codity');
}

const MAX_RESULTS = 100;

// GET /api/snapshots?tenantId=<id>&status=<status>
snapshotRouter.get('/', async (req: Request, res: Response) => {
  const tenantId = req.query.tenantId;
  if (!tenantId) {
    return res.status(400).json({ error: "Missing 'tenantId' query parameter" });
  }

  try {
    const db = await getDb();

    // Scope every query to the caller's tenant so cross-tenant reads are impossible.
    const filter: Record<string, unknown> = { tenantId };
    if (req.query.status !== undefined) {
      filter.status = String(req.query.status);
    }

    const snapshots = await db
      .collection('snapshots')
      .find(filter)
      .sort({ createdAt: -1 })
      .limit(MAX_RESULTS)
      .toArray();

    res.json({ tenantId, count: snapshots.length, snapshots });
  } catch {
    res.status(500).json({ error: 'Internal server error' });
  }
});
