#!/usr/bin/env bash
# Activate n8n workflows 4 and 5 in PostgreSQL
# Run this on the VPS: bash /opt/jarvis-repo/scripts/activate-workflows-4-5.sh

set -euo pipefail

REPO="/opt/jarvis-repo"
WF4_ID="a1b2c3d4-e5f6-7890-abcd-ef1234567804"
WF5_ID="a1b2c3d4-e5f6-7890-abcd-ef1234567805"

echo "=== Activating n8n Workflows 4 and 5 ==="

# Copy workflow files into postgres container for pg_read_file
docker cp "${REPO}/n8n/workflows/04-daily-briefing-push.json" jarvis-postgres:/tmp/wf4.json
docker cp "${REPO}/n8n/workflows/05-weekly-digest.json" jarvis-postgres:/tmp/wf5.json

echo "Files copied to postgres container"

# Build activation SQL
docker exec -i jarvis-postgres psql -U jarvis -d n8n << 'ENDSQL'
DO $$
DECLARE
  wf4 jsonb;
  wf5 jsonb;
  wf4_nodes jsonb;
  wf5_nodes jsonb;
  wf4_settings jsonb;
  wf5_settings jsonb;
  wf4_tags jsonb;
  wf5_tags jsonb;
  uid text;
BEGIN

  wf4 := pg_read_file('/tmp/wf4.json')::jsonb;
  wf5 := pg_read_file('/tmp/wf5.json')::jsonb;

  wf4_nodes    := wf4->'nodes';
  wf4_settings := wf4->'settings';
  wf4_tags     := '[]'::jsonb;

  wf5_nodes    := wf5->'nodes';
  wf5_settings := wf5->'settings';
  wf5_tags     := '[]'::jsonb;

  -- Insert workflow 4
  IF NOT EXISTS (SELECT 1 FROM workflow_entity WHERE id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567804') THEN
    INSERT INTO workflow_entity (id, name, active, nodes, connections, settings, "staticData", "pinData", "versionId", "triggerCount", "createdAt", "updatedAt")
    VALUES (
      'a1b2c3d4-e5f6-7890-abcd-ef1234567804',
      'JARVIS — Daily Briefing Push',
      true,
      wf4_nodes,
      wf4->'connections',
      COALESCE(wf4_settings, '{}'::jsonb),
      '{}'::jsonb,
      '{}'::jsonb,
      gen_random_uuid()::text,
      0,
      NOW(),
      NOW()
    );
    RAISE NOTICE 'Inserted workflow 4';
  ELSE
    UPDATE workflow_entity SET
      name = 'JARVIS — Daily Briefing Push',
      active = true,
      nodes = wf4_nodes,
      connections = wf4->'connections',
      settings = COALESCE(wf4_settings, '{}'::jsonb),
      "updatedAt" = NOW()
    WHERE id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567804';
    RAISE NOTICE 'Updated workflow 4';
  END IF;

  -- Insert workflow 5
  IF NOT EXISTS (SELECT 1 FROM workflow_entity WHERE id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567805') THEN
    INSERT INTO workflow_entity (id, name, active, nodes, connections, settings, "staticData", "pinData", "versionId", "triggerCount", "createdAt", "updatedAt")
    VALUES (
      'a1b2c3d4-e5f6-7890-abcd-ef1234567805',
      'JARVIS — Weekly Memory Digest',
      true,
      wf5_nodes,
      wf5->'connections',
      COALESCE(wf5_settings, '{}'::jsonb),
      '{}'::jsonb,
      '{}'::jsonb,
      gen_random_uuid()::text,
      0,
      NOW(),
      NOW()
    );
    RAISE NOTICE 'Inserted workflow 5';
  ELSE
    UPDATE workflow_entity SET
      name = 'JARVIS — Weekly Memory Digest',
      active = true,
      nodes = wf5_nodes,
      connections = wf5->'connections',
      settings = COALESCE(wf5_settings, '{}'::jsonb),
      "updatedAt" = NOW()
    WHERE id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567805';
    RAISE NOTICE 'Updated workflow 5';
  END IF;

  -- Ensure shared_workflow entries exist (project ownership)
  IF NOT EXISTS (SELECT 1 FROM shared_workflow WHERE "workflowId" = 'a1b2c3d4-e5f6-7890-abcd-ef1234567804') THEN
    -- Get an existing project ID from shared_workflow
    SELECT "projectId" INTO uid FROM shared_workflow LIMIT 1;
    IF uid IS NOT NULL THEN
      INSERT INTO shared_workflow ("workflowId", "projectId", role, "createdAt", "updatedAt")
      VALUES ('a1b2c3d4-e5f6-7890-abcd-ef1234567804', uid, 'workflow:owner', NOW(), NOW());
    END IF;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM shared_workflow WHERE "workflowId" = 'a1b2c3d4-e5f6-7890-abcd-ef1234567805') THEN
    SELECT "projectId" INTO uid FROM shared_workflow LIMIT 1;
    IF uid IS NOT NULL THEN
      INSERT INTO shared_workflow ("workflowId", "projectId", role, "createdAt", "updatedAt")
      VALUES ('a1b2c3d4-e5f6-7890-abcd-ef1234567805', uid, 'workflow:owner', NOW(), NOW());
    END IF;
  END IF;

END $$;
ENDSQL

echo ""
echo "=== Verification ==="
docker exec jarvis-postgres psql -U jarvis -d n8n -c \
  "SELECT id, name, active FROM workflow_entity ORDER BY \"createdAt\";"

echo ""
echo "=== Restarting n8n to pick up new workflows ==="
docker restart jarvis-n8n
sleep 12

echo ""
echo "=== Also update existing workflows 1-3 with dynamic bodies ==="
# Copy updated workflow files for 1-3
docker cp "${REPO}/n8n/workflows/01-health-alert.json" jarvis-postgres:/tmp/wf1.json
docker cp "${REPO}/n8n/workflows/02-github-activity.json" jarvis-postgres:/tmp/wf2.json
docker cp "${REPO}/n8n/workflows/03-metrics-snapshot.json" jarvis-postgres:/tmp/wf3.json

docker exec -i jarvis-postgres psql -U jarvis -d n8n << 'ENDSQL2'
UPDATE workflow_entity SET
  nodes = (pg_read_file('/tmp/wf1.json')::jsonb)->'nodes',
  connections = (pg_read_file('/tmp/wf1.json')::jsonb)->'connections',
  "updatedAt" = NOW()
WHERE id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567801';

UPDATE workflow_entity SET
  nodes = (pg_read_file('/tmp/wf2.json')::jsonb)->'nodes',
  connections = (pg_read_file('/tmp/wf2.json')::jsonb)->'connections',
  "updatedAt" = NOW()
WHERE id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567802';

UPDATE workflow_entity SET
  nodes = (pg_read_file('/tmp/wf3.json')::jsonb)->'nodes',
  connections = (pg_read_file('/tmp/wf3.json')::jsonb)->'connections',
  "updatedAt" = NOW()
WHERE id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567803';

SELECT 'Workflows 1-3 updated with dynamic bodies' AS status;
ENDSQL2

echo ""
echo "=== Final: all 5 workflows ==="
docker exec jarvis-postgres psql -U jarvis -d n8n -c \
  "SELECT name, active FROM workflow_entity ORDER BY name;"

echo ""
echo "✅ Done. All 5 JARVIS workflows active."
