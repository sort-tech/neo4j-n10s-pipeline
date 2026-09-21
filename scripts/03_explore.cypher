// ---------------------------------------------------------------------
// 적재 결과 확인 및 온톨로지 활용 예제 쿼리 (순수 Cypher)
//
// 실행:
//   docker compose exec -T neo4j \
//     cypher-shell -u neo4j -p password < scripts/03_explore.cypher
//
// 주의: 인스턴스에는 rdf:type 으로 명시한 라벨만 붙습니다. 즉
// `ex:graphMemory a demo:ProductProject` 는 `:ProductProject` 만 갖고
// `:Project` 는 갖지 않습니다. "모든 Project" 를 구하려면 T-Box 의
// SCO 계층을 타야 합니다 (5번, 7번 쿼리 참고).
// ---------------------------------------------------------------------

// 1. 스키마 노드 수 (T-Box)
MATCH (c:Class)
RETURN 'Class' AS kind, count(c) AS n
UNION ALL
MATCH (r:Relationship)
RETURN 'Relationship' AS kind, count(r) AS n
UNION ALL
MATCH (p:Property)
RETURN 'Property' AS kind, count(p) AS n;

// 2. 클래스 계층 (rdfs:subClassOf -> SCO)
MATCH path = (leaf:Class)-[:SCO*]->(root:Class)
WHERE NOT (root)-[:SCO]->(:Class)
RETURN root.name AS root, leaf.name AS subclass, length(path) AS depth
ORDER BY root, depth, subclass;

// 3. 오브젝트 프로퍼티의 domain/range
MATCH (r:Relationship)
OPTIONAL MATCH (r)-[:DOMAIN]->(d:Class)
OPTIONAL MATCH (r)-[:RANGE]->(g:Class)
RETURN r.name AS property, d.name AS domain, g.name AS range
ORDER BY property;

// 4. 인스턴스 개수 — 직접 부여된 라벨 기준
MATCH (n:Resource)
WHERE NOT n:Class AND NOT n:Relationship AND NOT n:Property
UNWIND labels(n) AS lbl
WITH lbl, count(*) AS n
WHERE lbl <> 'Resource'
RETURN lbl AS label, n
ORDER BY n DESC, label;

// 5. 온톨로지를 쓴 추론 질의 — "모든 Person"
//
// Engineer / Researcher / Student 에는 :Person 라벨이 없습니다.
// T-Box 의 SCO 를 따라가면 라벨을 추가하지 않고도 전부 모을 수 있습니다.
MATCH (:Class {name: 'Person'})<-[:SCO*0..]-(sub:Class)
WITH collect(sub.name) AS personClasses
MATCH (p:Resource)
WHERE any(l IN labels(p) WHERE l IN personClasses)
RETURN p.label AS person,
       [l IN labels(p) WHERE l <> 'Resource'] AS classes
ORDER BY person;

// 6. 상위 프로퍼티 추론 — affiliatedWith
//
// worksFor / studiesAt 는 affiliatedWith 의 하위 프로퍼티(SPO)입니다.
// affiliatedWith 관계 자체는 저장되어 있지 않지만 SPO 로 유도됩니다.
MATCH (:Relationship {name: 'affiliatedWith'})<-[:SPO*0..]-(sub:Relationship)
WITH collect(sub.name) AS subProps
MATCH (p:Resource)-[r]->(o:Resource)
WHERE type(r) IN subProps
RETURN p.label AS person, type(r) AS storedAs, o.label AS organization
ORDER BY person;

// 7. 스킬 갭 — 프로젝트가 요구하지만 참여 인원이 아무도 갖지 않은 역량
//
// count(person) 을 쓰는 이유: OPTIONAL MATCH 뒤의 count(*) 는 매칭이
// 없어도 1 이 되므로 0 과 비교할 수 없습니다.
MATCH (proj:Resource)-[:requiresSkill]->(need:Resource)
OPTIONAL MATCH (proj)<-[:contributesTo|leads]-(person:Resource)-[:hasSkill]->(need)
WITH proj, need, count(person) AS covered
WHERE covered = 0
RETURN proj.label AS project, collect(need.label) AS missingSkills
ORDER BY project;

// 8. 조직별 인력/프로젝트 요약
MATCH (org:Resource)
WHERE org.foundedIn IS NOT NULL
OPTIONAL MATCH (org)<-[:worksFor|studiesAt]-(member:Resource)
OPTIONAL MATCH (org)<-[:ownedBy]-(proj:Resource)
RETURN org.label            AS organization,
       count(DISTINCT member) AS members,
       count(DISTINCT proj)   AS projects
ORDER BY members DESC, organization;
