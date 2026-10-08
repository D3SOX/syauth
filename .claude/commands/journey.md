---
name: journey
description: Journey-based feature requirements with CJM
---

# JOURNEY-<date>: <description>

<!-- Template for /implement only: copy to specs/journeys/JOURNEY-{id}.md and complete every section. This file is not an Agent Skill. -->

## Roadmap link
- Source roadmap: <source_roadmap_link>
- Feature: <feature_name>

## 1. Journey

When <user persona and context> I want to <action or capability> so I can <outcome or value delivered>.

## 2. CJM

<Brief context paragraph: who the user is, what they are trying to do, what friction exists today, and how this feature removes that friction.>

### Phase 1: <phase_name>

User intent. <What the user is trying to accomplish in this phase.>

Actions. <Concrete steps the user takes.>

Pain / risk. <What could go wrong, what is confusing, what could fail. At least 3 scenarios per phase.>

Success signal. <Observable evidence that this phase completed correctly.>

### Phase 2: <phase_name>

User intent. <What the user is trying to accomplish in this phase.>

Actions. <Concrete steps the user takes.>

Pain / risk. <What could go wrong, what is confusing, what could fail. At least 3 scenarios per phase.>

Success signal. <Observable evidence that this phase completed correctly.>

### Phase 3: <phase_name>

User intent. <What the user is trying to accomplish in this phase.>

Actions. <Concrete steps the user takes.>

Pain / risk. <What could go wrong, what is confusing, what could fail. At least 3 scenarios per phase.>

Success signal. <Observable evidence that this phase completed correctly.>

<!-- Add more phases as needed. Most journeys have 3-6 phases. -->

### Friction and opportunity

| Friction | Phase | Opportunity |
|----------|-------|-------------|
| <friction_1> | <phase> | <opportunity_1> |
| <friction_2> | <phase> | <opportunity_2> |
| <friction_3> | <phase> | <opportunity_3> |

### Expected outcome

<One paragraph describing the ideal end state when this journey is fully realized. What does success look like from the user's perspective?>

## 3. UX implementation and assessment

### Time to first value
- [ ] <Metric: how fast the user gets value from this feature>
- [ ] <Metric: onboarding speed>

### Onboarding clarity
- [ ] <Checkpoint: is the feature discoverable?>
- [ ] <Checkpoint: are error messages clear?>

### Production-ready defaults
- [ ] <Checkpoint: are defaults safe and useful?>
- [ ] <Checkpoint: does the feature work without configuration?>

### Success path checks
- [ ] <Checkpoint: does the success path work end-to-end?>
- [ ] <Checkpoint: is the output correct and complete?>

### Decision load
- [ ] <Checkpoint: are choices minimized to what matters?>
- [ ] <Checkpoint: do sensible defaults reduce decisions?>

### Progressive complexity
- [ ] <Checkpoint: does the simple case stay simple?>
- [ ] <Checkpoint: are advanced features opt-in, not in the way?>

### Error quality
- [ ] <Checkpoint: do errors name the problem and suggest a fix?>
- [ ] <Checkpoint: are edge cases handled gracefully?>

### Failure safety
- [ ] <Checkpoint: is the feature recoverable from mistakes?>
- [ ] <Checkpoint: are destructive operations guarded?>

### Runtime transparency
- [ ] <Checkpoint: can the user see what is happening during execution?>
- [ ] <Checkpoint: is there no hidden state or silent side effects?>

### Debuggability
- [ ] <Checkpoint: can the user trace output back to input?>
- [ ] <Checkpoint: are intermediate artifacts inspectable?>

### Consistency across interfaces
- [ ] <Checkpoint: does the feature behave the same across agents/surfaces?>
- [ ] <Checkpoint: is terminology consistent across all generated files?>

### Workflow consistency
- [ ] <Checkpoint: does the feature follow established patterns in the project?>
- [ ] <Checkpoint: are artifact structures predictable across invocations?>

### Change safety
- [ ] <Checkpoint: are changes previewed before applying?>
- [ ] <Checkpoint: do updates avoid silently overwriting user customizations?>

### Experimentation safety
- [ ] <Checkpoint: can the user try things without risk to production state?>
- [ ] <Checkpoint: are experimental changes measurable and revertible?>

### Interaction latency
- [ ] <Checkpoint: does the feature complete without unnecessary delays?>
- [ ] <Checkpoint: is feedback immediate at each step?>

### Developer feedback speed
- [ ] <Checkpoint: are errors and results reported as they occur?>
- [ ] <Checkpoint: can the user course-correct without restarting?>

### Team scale
- [ ] <Checkpoint: can config and artifacts be shared via version control?>
- [ ] <Checkpoint: do standards apply uniformly across team members?>

### System scale
- [ ] <Checkpoint: does the feature work as the codebase grows?>
- [ ] <Checkpoint: is the architecture extensible without structural changes?>

### Right behavior by default
- [ ] <Checkpoint: does the feature do the right thing without configuration?>
- [ ] <Checkpoint: are safe defaults chosen over permissive ones?>

### Anti-bypass design
- [ ] <Checkpoint: are quality gates enforced, not optional?>
- [ ] <Checkpoint: is there no easy way to skip safety checks?>

## 4. Tests

### TC-01: <test_name>

Given <precondition>.
When <action>.
Then <expected outcome>.

### TC-02: <test_name>

Given <precondition>.
When <action>.
Then <expected outcome>.

### TC-03: <test_name>

Given <precondition>.
When <action>.
Then <expected outcome>.

<!-- Add more test cases as needed. Most journeys have 5-15 test cases. -->

## Traceability
- Roadmap item: <link to roadmap item in specs/>
- Implementation files: <to be filled by /implement>
- Test files: <to be filled by /implement>
