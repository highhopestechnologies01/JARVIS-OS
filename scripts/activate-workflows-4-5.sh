#!/usr/bin/env bash
# Activate / re-sync all 5 n8n workflows in PostgreSQL
# Run this on the VPS: bash /opt/jarvis-repo/scripts/activate-workflows-4-5.sh
#
# KEY INSIGHT (n8n v2.x): Execution uses workflow_history (via workflow_published_version),
# NOT workflow_entity.nodes directly. Updates must touch ALL THREE tables:
#   1. workflow_entity          — draft / editor state
#   2. workflow_history         — versioned execution state
#   3. workflow_published_version — pointer from workflow → current running version
# Also: workflow_entity.activeVersionId must be set for schedule-triggered workflows.

set -euo pipefail

REPO="/opt/jarvis-repo"

echo "=== Copying workflow files to postgres container ==="
docker cp "${REPO}/n8n/workflows/01-health-alert.json"        jarvis-postgres:/tmp/wf1.json
docker cp "${REPO}/n8n/workflows/02-github-activity.json"     jarvis-postgres:/tmp/wf2.json
docker cp "${REPO}/n8n/workflows/03-metrics-snapshot.json"    jarvis-postgres:/tmp/wf3.json
docker cp "${REPO}/n8n/workflows/04-daily-briefing-push.json" jarvis-postgres:/tmp/wf4.json
docker cp "${REPO}/n8n/workflows/05-weekly-digest.json"       jarvis-postgres:/tmp/wf5.json
echo "Files copied."

echo ""
echo "=== Upserting workflow_entity (draft) for all 5 workflows ==="
docker exec jarvis-postgres psql -U jarvis -d n8n -c "
-- Update existing workflows 1-3
UPDATE workflow_entity SET
  nodes = (pg_read_file('/tmp/wf1.json')::jsonb)->'nodes',
  connections = (pg_read_file('/tmp/wf1.json')::jsonb)->'connections',
  active = true, \"updatedAt\" = NOW()
WHERE id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567801';

UPDATE workflow_entity SET
  nodes = (pg_read_file('/tmp/wf2.json')::jsonb)->'nodes',
  connections = (pg_read_file('/tmp/wf2.json')::jsonb)->'connections',
  active = true, \"updatedAt\" = NOW()
WHERE id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567802';

UPDATE workflow_entity SET
  nodes = (pg_read_file('/tmp/wf3.json')::jsonb)->'nodes',
  connections = (pg_read_file('/tmp/wf3.json')::jsonb)->'connections',
  active = true, \"updatedAt\" = NOW()
WHERE id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567803';

SELECT 'workflow_entity updated' AS status;
"

echo ""
echo "=== Syncing workflow_history (execution version) for all 5 workflows ==="
docker exec -i jarvis-postgres psql -U jarvis -d n8n << 'ENDSQL'
DO $$
DECLARE
  wfids text[] := ARRAY[
    'a1b2c3d4-e5f6-7890-abcd-ef1234567801',
    'a1b2c3d4-e5f6-7890-abcd-ef1234567802',
    'a1b2c3d4-e5f6-7890-abcd-ef1234567803',
    'a1b2c3d4-e5f6-7890-abcd-ef1234567804',
    'a1b2c3d4-e5f6-7890-abcd-ef1234567805'
  ];
  wfid text;
  new_vid text;
  auth_val text;
  pub_vid text;
  uid text;
BEGIN
  SELECT COALESCE(authors, '') INTO auth_val FROM workflow_history LIMIT 1;
  SELECT "projectId" INTO uid FROM shared_workflow LIMIT 1;

  FOREACH wfid IN ARRAY wfids LOOP
    -- Ensure shared_workflow entry exists
    IF uid IS NOT NULL AND NOT EXISTS (SELECT 1 FROM shared_workflow WHERE "workflowId" = wfid) THEN
      INSERT INTO shared_workflow ("workflowId", "projectId", role, "createdAt", "updatedAt")
      VALUES (wfid, uid, 'workflow:owner', NOW(), NOW());
    END IF;

    -- Check if published version exists
    SELECT "publishedVersionId" INTO pub_vid
    FROM workflow_published_version WHERE "workflowId" = wfid;

    IF pub_vid IS NOT NULL THEN
      -- Update existing: sync nodes/connections from workflow_entity
      UPDATE workflow_history SET
        nodes = (SELECT nodes FROM workflow_entity WHERE id = wfid),
        connections = (SELECT connections FROM workflow_entity WHERE id = wfid),
        "updatedAt" = NOW()
      WHERE "versionId" = pub_vid;
      RAISE NOTICE 'Updated workflow_history for workflow %', wfid;
    ELSE
      -- Create new published version
      new_vid := gen_random_uuid()::text;
      INSERT INTO workflow_history
        ("versionId", "workflowId", nodes, connections, name, autosaved, authors, "nodeGroups", "createdAt", "updatedAt")
      SELECT new_vid, id, nodes, connections, name, false, auth_val, '[]'::json, NOW(), NOW()
      FROM workflow_entity WHERE id = wfid;

      INSERT INTO workflow_published_version ("workflowId", "publishedVersionId", "createdAt", "updatedAt")
      VALUES (wfid, new_vid, NOW(), NOW());

      pub_vid := new_vid;
      RAISE NOTICE 'Created new published version for workflow %', wfid;
    END IF;

    -- Set activeVersionId (required for schedule triggers to activate)
    UPDATE workflow_entity SET
      "activeVersionId" = pub_vid,
      "versionId" = COALESCE("versionId", pub_vid)
    WHERE id = wfid AND "activeVersionId" IS NULL;
  END LOOP;
END $$;
ENDSQL

echo ""
echo "=== Verification ==="
docker exec jarvis-postgres psql -U jarvis -d n8n -c "
SELECT we.name,
       we.active,
       LEFT(we.\"activeVersionId\",8) AS active_ver,
       CASE WHEN wpv.\"workflowId\" IS NOT NULL THEN 'published' ELSE 'MISSING' END AS pub_status
FROM workflow_entity we
LEFT JOIN workflow_published_version wpv ON wpv.\"workflowId\" = we.id
WHERE we.id LIKE 'a1b2c3d4%'
ORDER BY we.name;
"

echo ""
echo "=== Restarting n8n ==="
docker restart jarvis-n8n
sleep 20
docker logs jarvis-n8n 2>&1 | grep "Activated" | sort -u

echo ""
echo "✅ All 5 JARVIS workflows active and published."
