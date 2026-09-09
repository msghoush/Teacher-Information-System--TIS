from datetime import datetime
import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, LargeBinary, String, Text, UniqueConstraint, text
from sqlalchemy.orm import relationship
from database import Base
from workspace_classification import WorkspaceClassification, WorkspaceLifecycleStatus


class Branch(Base):
    __tablename__ = "branches"
    __table_args__ = (
        UniqueConstraint("id", "school_group_id", name="uq_branches_id_school_group"),
    )
    id = Column(Integer, primary_key=True, index=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), index=True)
    name = Column(String, nullable=False)
    location = Column(String)
    country_code = Column(String(2))
    country_name = Column(String(120))
    region_name = Column(String(160))
    city_name = Column(String(160))
    district_name = Column(String(160))
    neighborhood_name = Column(String(160))
    status = Column(Boolean, default=True)


class SchoolGroup(Base):
    __tablename__ = "school_groups"
    __table_args__ = (
        CheckConstraint(
            "workspace_classification IN ('internal_sandbox','customer_demo','customer_paid','customer')",
            name="ck_school_groups_workspace_classification",
        ),
        CheckConstraint(
            "workspace_lifecycle_status IN ('provisioning','active','suspended','archived')",
            name="ck_school_groups_workspace_lifecycle_status",
        ),
        Index("uq_school_groups_workspace_uuid", "workspace_uuid", unique=True),
        Index("ix_school_groups_workspace_classification", "workspace_classification"),
        Index("ix_school_groups_workspace_lifecycle_status", "workspace_lifecycle_status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(160), nullable=False, unique=True)
    workspace_uuid = Column(String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    workspace_classification = Column(
        String(32), nullable=False, default=WorkspaceClassification.INTERNAL_SANDBOX.value
    )
    workspace_lifecycle_status = Column(
        String(20), nullable=False, default=WorkspaceLifecycleStatus.ACTIVE.value
    )
    country_code = Column(String(2))
    country_name = Column(String(120))
    region_name = Column(String(160))
    city_name = Column(String(160))
    district_name = Column(String(160))
    neighborhood_name = Column(String(160))
    status = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TenantProfile(Base):
    __tablename__ = "tenant_profiles"
    __table_args__ = (
        UniqueConstraint("school_group_id", name="uq_tenant_profiles_school_group"),
        Index("ix_tenant_profiles_school_group", "school_group_id"),
    )

    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False, index=True)
    legal_name = Column(String(180))
    website = Column(String(180))
    timezone = Column(String(80))
    educational_program = Column(String(20))
    school_type = Column(String(120))
    estimated_staff_users = Column(Integer)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SchoolGroupLogo(Base):
    __tablename__ = "school_group_logos"
    __table_args__ = (
        UniqueConstraint("school_group_id", "slot_key", name="uq_school_group_logos_group_slot"),
        Index("ix_school_group_logos_group", "school_group_id"),
    )

    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False, index=True)
    slot_key = Column(String(40), nullable=False)
    label = Column(String(120), nullable=False)
    image_path = Column(String(255), nullable=False)
    content_type = Column(String(80))
    sort_order = Column(Integer, nullable=False, default=0)
    updated_by_user_id = Column(String(10))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        Index("ix_role_permissions_scope_role", "school_group_id", "role"),
        Index("ix_role_permissions_key", "permission_key"),
    )

    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), index=True)
    role = Column(String(50), nullable=False, index=True)
    permission_key = Column(String(120), nullable=False, index=True)
    is_allowed = Column(Boolean, nullable=False, default=False)
    updated_by_user_id = Column(String(10))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SystemDesignSetting(Base):
    __tablename__ = "system_design_settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(80), nullable=False, unique=True, index=True)
    value = Column(String(120), nullable=False, default="")
    updated_by_user_id = Column(String(10))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class VisualDesignSetting(Base):
    __tablename__ = "visual_design_settings"
    __table_args__ = (
        UniqueConstraint("page_key", "component_key", "setting_key", name="uq_visual_design_component_setting"),
        Index("ix_visual_design_page_component", "page_key", "component_key"),
    )

    id = Column(Integer, primary_key=True)
    page_key = Column(String(80), nullable=False, index=True)
    component_key = Column(String(120), nullable=False, index=True)
    component_type = Column(String(40), nullable=False)
    setting_key = Column(String(80), nullable=False)
    setting_value = Column(String(255), nullable=False, default="")
    scope_type = Column(String(20), nullable=False, default="global")
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    updated_by_user_id = Column(String(10))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class BranchLogo(Base):
    __tablename__ = "branch_logos"
    __table_args__ = (
        UniqueConstraint("branch_id", "slot_key", name="uq_branch_logos_branch_slot"),
        Index("ix_branch_logos_branch", "branch_id"),
    )

    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    slot_key = Column(String(40), nullable=False)
    label = Column(String(120), nullable=False)
    image_path = Column(String(255), nullable=False)
    content_type = Column(String(80))
    sort_order = Column(Integer, nullable=False, default=0)
    updated_by_user_id = Column(String(10))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AcademicYear(Base):
    __tablename__ = "academic_years"
    __table_args__ = (
        UniqueConstraint("id", "school_group_id", name="uq_academic_years_id_school_group"),
    )
    id = Column(Integer, primary_key=True, index=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), index=True)
    year_name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        CheckConstraint("status IN ('active','inactive')", name="ck_students_status"),
        UniqueConstraint("id", "school_group_id", name="uq_students_id_school_group"),
        Index("ix_students_group_name", "school_group_id", "last_name", "first_name"),
    )

    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False, index=True)
    first_name = Column(String(100), nullable=False)
    father_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=False)
    gender = Column(String(24), nullable=True)
    status = Column(String(16), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    updated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)


class StudentExternalIdentifier(Base):
    __tablename__ = "student_external_identifiers"
    __table_args__ = (
        CheckConstraint("status IN ('active','inactive')", name="ck_student_external_identifiers_status"),
        ForeignKeyConstraint(
            ["student_id", "school_group_id"], ["students.id", "students.school_group_id"],
            name="fk_student_external_identifiers_student_scope",
        ),
        UniqueConstraint("school_group_id", "namespace", "value", name="uq_student_external_identifiers_scope_namespace_value"),
        Index("ix_student_external_identifiers_student", "school_group_id", "student_id"),
    )

    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    student_id = Column(Integer, nullable=False)
    namespace = Column(String(80), nullable=False)
    value = Column(String(180), nullable=False)
    source = Column(String(120), nullable=True)
    status = Column(String(16), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class StudentAcademicPlacement(Base):
    __tablename__ = "student_academic_placements"
    __table_args__ = (
        CheckConstraint("status IN ('active','ended')", name="ck_student_academic_placements_status"),
        CheckConstraint("grade_level IN ('KG','1','2','3','4','5','6','7','8','9','10','11','12')", name="ck_student_academic_placements_grade"),
        CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="ck_student_academic_placements_range"),
        ForeignKeyConstraint(["student_id", "school_group_id"], ["students.id", "students.school_group_id"], name="fk_student_academic_placements_student_scope"),
        ForeignKeyConstraint(["branch_id", "school_group_id"], ["branches.id", "branches.school_group_id"], name="fk_student_academic_placements_branch_scope"),
        ForeignKeyConstraint(["academic_year_id", "school_group_id"], ["academic_years.id", "academic_years.school_group_id"], name="fk_student_academic_placements_year_scope"),
        UniqueConstraint("id", "student_id", "academic_year_id", "branch_id", "school_group_id", name="uq_student_academic_placements_frozen_scope"),
        Index("ix_student_academic_placements_student_time", "school_group_id", "student_id", "effective_from"),
        Index("ix_student_academic_placements_scope", "school_group_id", "branch_id", "academic_year_id"),
    )

    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    student_id = Column(Integer, nullable=False)
    academic_year_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=False)
    planning_section_id = Column(Integer, ForeignKey("planning_sections.id", ondelete="SET NULL"), nullable=True)
    grade_level = Column(String(8), nullable=False)
    section_name = Column(String(20), nullable=False)
    effective_from = Column(DateTime, nullable=False)
    effective_to = Column(DateTime, nullable=True)
    status = Column(String(16), nullable=False, default="active")
    reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    updated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)


class StudentAudit(Base):
    __tablename__ = "student_audits"
    __table_args__ = (
        CheckConstraint("resource_type IN ('student','external_identifier','academic_placement')", name="ck_student_audits_resource_type"),
        ForeignKeyConstraint(["student_id", "school_group_id"], ["students.id", "students.school_group_id"], name="fk_student_audits_student_scope"),
        Index("ix_student_audits_scope_resource", "school_group_id", "student_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(String(36), nullable=False, default=lambda: str(uuid.uuid4()), unique=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    student_id = Column(Integer, nullable=False)
    actor_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    actor_branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)
    resource_type = Column(String(32), nullable=False)
    resource_id = Column(Integer, nullable=False)
    action = Column(String(40), nullable=False)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)
    correlation_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TalentProgram(Base):
    __tablename__ = "talent_programs"
    __table_args__ = (
        CheckConstraint("status IN ('draft','active','retired')", name="ck_talent_programs_status"),
        UniqueConstraint("id", "school_group_id", name="uq_talent_programs_id_school_group"),
        UniqueConstraint("school_group_id", "name", name="uq_talent_programs_group_name"),
        Index("ix_talent_programs_group_status", "school_group_id", "status"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    name = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="draft")
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    updated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TalentProgramAcademicYearConfiguration(Base):
    __tablename__ = "talent_program_academic_year_configurations"
    __table_args__ = (
        ForeignKeyConstraint(["program_id", "school_group_id"], ["talent_programs.id", "talent_programs.school_group_id"], name="fk_talent_program_year_configs_program_scope"),
        ForeignKeyConstraint(["academic_year_id", "school_group_id"], ["academic_years.id", "academic_years.school_group_id"], name="fk_talent_program_year_configs_year_scope"),
        UniqueConstraint("program_id", "academic_year_id", name="uq_talent_program_year_configs_program_year"),
        UniqueConstraint("id", "program_id", "academic_year_id", "school_group_id", name="uq_talent_program_year_configs_plan_scope"),
        Index("ix_talent_program_year_configs_scope", "school_group_id", "academic_year_id"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    program_id = Column(Integer, nullable=False)
    academic_year_id = Column(Integer, nullable=False)
    is_enabled = Column(Boolean, nullable=False, default=True)
    eligible_grade_levels_csv = Column(String(80), nullable=False)
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    updated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TalentProgramFrameworkVersion(Base):
    __tablename__ = "talent_program_framework_versions"
    __table_args__ = (
        CheckConstraint("status IN ('draft','active','retired')", name="ck_talent_framework_versions_status"),
        CheckConstraint("revision >= 1", name="ck_talent_framework_versions_revision"),
        CheckConstraint("supersedes_framework_version_id IS NULL OR supersedes_framework_version_id <> id", name="ck_talent_framework_versions_not_self_superseding"),
        ForeignKeyConstraint(["program_id", "school_group_id"], ["talent_programs.id", "talent_programs.school_group_id"], name="fk_talent_framework_versions_program_scope"),
        ForeignKeyConstraint(
            ["supersedes_framework_version_id", "program_id", "school_group_id"],
            ["talent_program_framework_versions.id", "talent_program_framework_versions.program_id", "talent_program_framework_versions.school_group_id"],
            name="fk_talent_framework_versions_supersedes_scope",
        ),
        UniqueConstraint("id", "program_id", "school_group_id", name="uq_talent_framework_versions_id_program_scope"),
        UniqueConstraint("program_id", "version_number", name="uq_talent_framework_versions_program_number"),
        Index("ix_talent_framework_versions_history", "school_group_id", "program_id", "version_number"),
        Index("uq_talent_framework_versions_one_active", "program_id", unique=True,
              sqlite_where=text("status = 'active'"), postgresql_where=text("status = 'active'")),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    program_id = Column(Integer, nullable=False)
    version_number = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="draft")
    title = Column(String(180), nullable=False)
    summary = Column(Text, nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    semantic_fingerprint = Column(String(64), nullable=False)
    supersedes_framework_version_id = Column(Integer, nullable=True)
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    updated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    activated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    activated_at = Column(DateTime, nullable=True)
    retired_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    retired_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TalentCompetency(Base):
    __tablename__ = "talent_competencies"
    __table_args__ = (
        CheckConstraint("status IN ('active','retired')", name="ck_talent_competencies_status"),
        ForeignKeyConstraint(["program_id", "school_group_id"], ["talent_programs.id", "talent_programs.school_group_id"], name="fk_talent_competencies_program_scope"),
        UniqueConstraint("id", "program_id", "school_group_id", name="uq_talent_competencies_id_program_scope"),
        UniqueConstraint("program_id", "code", name="uq_talent_competencies_program_code"),
        Index("ix_talent_competencies_scope", "school_group_id", "program_id", "status"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    program_id = Column(Integer, nullable=False)
    code = Column(String(80), nullable=False)
    name = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="active")
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    updated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class FrameworkCompetency(Base):
    __tablename__ = "talent_framework_competencies"
    __table_args__ = (
        CheckConstraint("display_order >= 1", name="ck_talent_framework_competencies_order"),
        ForeignKeyConstraint(["framework_version_id", "program_id", "school_group_id"], ["talent_program_framework_versions.id", "talent_program_framework_versions.program_id", "talent_program_framework_versions.school_group_id"], name="fk_talent_framework_competencies_framework_scope"),
        ForeignKeyConstraint(["talent_competency_id", "program_id", "school_group_id"], ["talent_competencies.id", "talent_competencies.program_id", "talent_competencies.school_group_id"], name="fk_talent_framework_competencies_competency_scope"),
        UniqueConstraint("id", "framework_version_id", "program_id", "school_group_id", name="uq_talent_framework_competencies_id_scope"),
        UniqueConstraint("framework_version_id", "talent_competency_id", name="uq_talent_framework_competencies_membership"),
        UniqueConstraint("framework_version_id", "display_order", name="uq_talent_framework_competencies_order"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    program_id = Column(Integer, nullable=False)
    framework_version_id = Column(Integer, nullable=False)
    talent_competency_id = Column(Integer, nullable=False)
    display_order = Column(Integer, nullable=False)
    label = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TalentRubric(Base):
    __tablename__ = "talent_rubrics"
    __table_args__ = (
        ForeignKeyConstraint(["framework_version_id", "program_id", "school_group_id"], ["talent_program_framework_versions.id", "talent_program_framework_versions.program_id", "talent_program_framework_versions.school_group_id"], name="fk_talent_rubrics_framework_scope"),
        UniqueConstraint("framework_version_id", name="uq_talent_rubrics_framework"),
        UniqueConstraint("id", "framework_version_id", "program_id", "school_group_id", name="uq_talent_rubrics_id_framework_scope"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    program_id = Column(Integer, nullable=False)
    framework_version_id = Column(Integer, nullable=False)
    name = Column(String(180), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TalentRubricLevel(Base):
    """A Framework-owned, configurable ordered rubric level.

    ``display_order`` is the single authority for both presentation order and
    the "rubric_level_at_or_above" semantic proficiency rank: lowest
    proficiency is display_order 1, and a rule targeting a given level means
    that level or any level with a greater display_order. It is dense (1..N),
    unique per rubric, and fully reindexed on add/remove/reorder, so there is
    no code path where a valid presentation position could diverge from a
    valid proficiency rank. Ranking never depends on ``numeric_value``, which
    stays optional so qualitative Programs (no KPI, no numeric levels) order
    and evaluate correctly. Reordering is Draft-only and always bumps the
    Framework revision/fingerprint (see talent_program_service.reorder_rubric_levels).
    """

    __tablename__ = "talent_rubric_levels"
    __table_args__ = (
        CheckConstraint("display_order >= 1", name="ck_talent_rubric_levels_order"),
        ForeignKeyConstraint(["rubric_id", "framework_version_id", "program_id", "school_group_id"], ["talent_rubrics.id", "talent_rubrics.framework_version_id", "talent_rubrics.program_id", "talent_rubrics.school_group_id"], name="fk_talent_rubric_levels_rubric_scope"),
        UniqueConstraint("id", "rubric_id", "framework_version_id", "program_id", "school_group_id", name="uq_talent_rubric_levels_id_scope"),
        UniqueConstraint("rubric_id", "code", name="uq_talent_rubric_levels_code"),
        UniqueConstraint("rubric_id", "display_order", name="uq_talent_rubric_levels_order"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    program_id = Column(Integer, nullable=False)
    framework_version_id = Column(Integer, nullable=False)
    rubric_id = Column(Integer, nullable=False)
    code = Column(String(80), nullable=False)
    label = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    display_order = Column(Integer, nullable=False)
    numeric_value = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TalentCompetencyRubricDescriptor(Base):
    __tablename__ = "talent_competency_rubric_descriptors"
    __table_args__ = (
        ForeignKeyConstraint(["framework_competency_id", "framework_version_id", "program_id", "school_group_id"], ["talent_framework_competencies.id", "talent_framework_competencies.framework_version_id", "talent_framework_competencies.program_id", "talent_framework_competencies.school_group_id"], name="fk_talent_descriptors_framework_competency_scope"),
        ForeignKeyConstraint(["rubric_level_id", "rubric_id", "framework_version_id", "program_id", "school_group_id"], ["talent_rubric_levels.id", "talent_rubric_levels.rubric_id", "talent_rubric_levels.framework_version_id", "talent_rubric_levels.program_id", "talent_rubric_levels.school_group_id"], name="fk_talent_descriptors_level_scope"),
        UniqueConstraint("framework_competency_id", "rubric_level_id", name="uq_talent_descriptors_competency_level"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    program_id = Column(Integer, nullable=False)
    framework_version_id = Column(Integer, nullable=False)
    rubric_id = Column(Integer, nullable=False)
    framework_competency_id = Column(Integer, nullable=False)
    rubric_level_id = Column(Integer, nullable=False)
    descriptor = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TalentKpiConfiguration(Base):
    """Optional, bounded, Framework-specific KPI configuration.

    ``calculation_method`` is a governed, closed enum of approved KPI
    calculation primitives - currently only ``weighted_level_average`` - not
    an open or scriptable rule/expression system. KPI is never required: a
    Program (e.g. a qualitative Performing Arts Framework) remains fully
    valid and activatable with no KPI configuration and no numeric rubric
    levels. When enabled, ``weighted_level_average`` is a bounded, optional,
    Framework-specific primitive only: it is not a universal Talent Score and
    is never cross-Program normalized. Inputs must be exact Framework
    Competencies of the same Framework Version, weights are positive basis
    points summing to exactly 10000, and every rubric level must carry an
    in-scale integer numeric_value only while this KPI stays enabled
    (talent_program_service._enforce_enabled_kpi_numeric_scale). Additional
    calculation primitives require future governed Product Owner approval and
    must extend this CHECK constraint explicitly; do not loosen it into a
    generic expression/scripting mechanism.
    """

    __tablename__ = "talent_kpi_configurations"
    __table_args__ = (
        CheckConstraint("calculation_method IN ('weighted_level_average')", name="ck_talent_kpi_configurations_method"),
        CheckConstraint("result_scale_max > result_scale_min", name="ck_talent_kpi_configurations_scale"),
        ForeignKeyConstraint(["framework_version_id", "program_id", "school_group_id"], ["talent_program_framework_versions.id", "talent_program_framework_versions.program_id", "talent_program_framework_versions.school_group_id"], name="fk_talent_kpi_configurations_framework_scope"),
        UniqueConstraint("framework_version_id", name="uq_talent_kpi_configurations_framework"),
        UniqueConstraint("id", "framework_version_id", "program_id", "school_group_id", name="uq_talent_kpi_configurations_id_scope"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    program_id = Column(Integer, nullable=False)
    framework_version_id = Column(Integer, nullable=False)
    is_enabled = Column(Boolean, nullable=False, default=True)
    calculation_method = Column(String(40), nullable=False, default="weighted_level_average")
    result_scale_min = Column(Integer, nullable=False)
    result_scale_max = Column(Integer, nullable=False)
    interpretation = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TalentKpiComponent(Base):
    __tablename__ = "talent_kpi_components"
    __table_args__ = (
        CheckConstraint("weight_basis_points > 0 AND weight_basis_points <= 10000", name="ck_talent_kpi_components_weight"),
        ForeignKeyConstraint(["kpi_configuration_id", "framework_version_id", "program_id", "school_group_id"], ["talent_kpi_configurations.id", "talent_kpi_configurations.framework_version_id", "talent_kpi_configurations.program_id", "talent_kpi_configurations.school_group_id"], name="fk_talent_kpi_components_config_scope"),
        ForeignKeyConstraint(["framework_competency_id", "framework_version_id", "program_id", "school_group_id"], ["talent_framework_competencies.id", "talent_framework_competencies.framework_version_id", "talent_framework_competencies.program_id", "talent_framework_competencies.school_group_id"], name="fk_talent_kpi_components_framework_competency_scope"),
        UniqueConstraint("kpi_configuration_id", "framework_competency_id", name="uq_talent_kpi_components_competency"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    program_id = Column(Integer, nullable=False)
    framework_version_id = Column(Integer, nullable=False)
    kpi_configuration_id = Column(Integer, nullable=False)
    framework_competency_id = Column(Integer, nullable=False)
    weight_basis_points = Column(Integer, nullable=False)


class TalentReviewCandidatePolicy(Base):
    __tablename__ = "talent_review_candidate_policies"
    __table_args__ = (
        CheckConstraint("match_mode IN ('all','any')", name="ck_talent_review_candidate_policies_mode"),
        ForeignKeyConstraint(["framework_version_id", "program_id", "school_group_id"], ["talent_program_framework_versions.id", "talent_program_framework_versions.program_id", "talent_program_framework_versions.school_group_id"], name="fk_talent_review_candidate_policies_framework_scope"),
        UniqueConstraint("framework_version_id", name="uq_talent_review_candidate_policies_framework"),
        UniqueConstraint("id", "framework_version_id", "program_id", "school_group_id", name="uq_talent_review_candidate_policies_id_scope"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    program_id = Column(Integer, nullable=False)
    framework_version_id = Column(Integer, nullable=False)
    is_enabled = Column(Boolean, nullable=False, default=True)
    match_mode = Column(String(8), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TalentReviewCandidateRule(Base):
    __tablename__ = "talent_review_candidate_rules"
    __table_args__ = (
        CheckConstraint("rule_type IN ('rubric_level_at_or_above','kpi_at_or_above')", name="ck_talent_review_candidate_rules_type"),
        CheckConstraint("display_order >= 1", name="ck_talent_review_candidate_rules_order"),
        CheckConstraint("(rule_type = 'rubric_level_at_or_above' AND rubric_level_id IS NOT NULL AND rubric_id IS NOT NULL AND framework_competency_id IS NOT NULL AND threshold_value IS NULL) OR (rule_type = 'kpi_at_or_above' AND rubric_level_id IS NULL AND rubric_id IS NULL AND framework_competency_id IS NULL AND threshold_value IS NOT NULL)", name="ck_talent_review_candidate_rules_shape"),
        ForeignKeyConstraint(["policy_id", "framework_version_id", "program_id", "school_group_id"], ["talent_review_candidate_policies.id", "talent_review_candidate_policies.framework_version_id", "talent_review_candidate_policies.program_id", "talent_review_candidate_policies.school_group_id"], name="fk_talent_review_candidate_rules_policy_scope"),
        ForeignKeyConstraint(["framework_competency_id", "framework_version_id", "program_id", "school_group_id"], ["talent_framework_competencies.id", "talent_framework_competencies.framework_version_id", "talent_framework_competencies.program_id", "talent_framework_competencies.school_group_id"], name="fk_talent_review_candidate_rules_competency_scope"),
        ForeignKeyConstraint(["rubric_level_id", "rubric_id", "framework_version_id", "program_id", "school_group_id"], ["talent_rubric_levels.id", "talent_rubric_levels.rubric_id", "talent_rubric_levels.framework_version_id", "talent_rubric_levels.program_id", "talent_rubric_levels.school_group_id"], name="fk_talent_review_candidate_rules_level_scope"),
        UniqueConstraint("policy_id", "display_order", name="uq_talent_review_candidate_rules_order"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    program_id = Column(Integer, nullable=False)
    framework_version_id = Column(Integer, nullable=False)
    policy_id = Column(Integer, nullable=False)
    rule_type = Column(String(40), nullable=False)
    display_order = Column(Integer, nullable=False)
    framework_competency_id = Column(Integer, nullable=True)
    rubric_id = Column(Integer, nullable=True)
    rubric_level_id = Column(Integer, nullable=True)
    threshold_value = Column(Integer, nullable=True)


class TalentConfigurationAudit(Base):
    __tablename__ = "talent_configuration_audits"
    __table_args__ = (
        # M3 governance closure: audit identity now targets the specific M3 child
        # resource that changed (matching the framework_competency precedent
        # already used by M2), not just the containing framework_version. See
        # db_migrations._talent_rubric_kpi_candidate_policy_foundation for the
        # accompanying widening of this constraint on already-created tables.
        CheckConstraint("resource_type IN ('program','annual_configuration','framework_version','competency','framework_competency','rubric','rubric_level','rubric_descriptor','kpi_configuration','kpi_component','review_candidate_policy','review_candidate_rule','annual_evaluation_plan','planned_evaluation_period')", name="ck_talent_configuration_audits_resource_type"),
        Index("ix_talent_configuration_audits_scope_resource", "school_group_id", "program_id", "created_at"),
    )
    id = Column(Integer, primary_key=True)
    public_id = Column(String(36), nullable=False, default=lambda: str(uuid.uuid4()), unique=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    program_id = Column(Integer, nullable=False)
    actor_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    actor_branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)
    resource_type = Column(String(40), nullable=False)
    resource_id = Column(Integer, nullable=False)
    action = Column(String(40), nullable=False)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)
    correlation_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TalentAnnualEvaluationPlan(Base):
    __tablename__ = "talent_annual_evaluation_plans"
    __table_args__ = (
        CheckConstraint("status IN ('draft','active','closed')", name="ck_talent_annual_evaluation_plans_status"),
        CheckConstraint("revision >= 1", name="ck_talent_annual_evaluation_plans_revision"),
        CheckConstraint("(status = 'draft' AND activated_at IS NULL AND closed_at IS NULL) OR (status = 'active' AND activated_at IS NOT NULL AND closed_at IS NULL) OR (status = 'closed' AND activated_at IS NOT NULL AND closed_at IS NOT NULL)", name="ck_talent_annual_evaluation_plans_lifecycle"),
        CheckConstraint("source_plan_id IS NULL OR source_plan_id <> id", name="ck_talent_annual_evaluation_plans_not_self_source"),
        ForeignKeyConstraint(
            ["program_academic_year_configuration_id", "program_id", "academic_year_id", "school_group_id"],
            ["talent_program_academic_year_configurations.id", "talent_program_academic_year_configurations.program_id", "talent_program_academic_year_configurations.academic_year_id", "talent_program_academic_year_configurations.school_group_id"],
            name="fk_talent_annual_evaluation_plans_config_scope",
        ),
        ForeignKeyConstraint(
            ["source_plan_id", "program_id", "school_group_id"],
            ["talent_annual_evaluation_plans.id", "talent_annual_evaluation_plans.program_id", "talent_annual_evaluation_plans.school_group_id"],
            name="fk_talent_annual_evaluation_plans_source_scope",
        ),
        UniqueConstraint("program_academic_year_configuration_id", name="uq_talent_annual_evaluation_plans_config"),
        UniqueConstraint("id", "program_id", "school_group_id", name="uq_talent_annual_evaluation_plans_program_scope"),
        UniqueConstraint("id", "program_id", "academic_year_id", "school_group_id", name="uq_talent_annual_evaluation_plans_cycle_scope"),
        Index("ix_talent_annual_evaluation_plans_scope", "school_group_id", "program_id", "academic_year_id", "status"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    program_id = Column(Integer, nullable=False)
    academic_year_id = Column(Integer, nullable=False)
    program_academic_year_configuration_id = Column(Integer, nullable=False)
    source_plan_id = Column(Integer, nullable=True)
    status = Column(String(16), nullable=False, default="draft")
    revision = Column(Integer, nullable=False, default=1)
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    activated_at = Column(DateTime, nullable=True)
    activated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    closed_at = Column(DateTime, nullable=True)
    closed_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TalentPlannedEvaluationPeriod(Base):
    __tablename__ = "talent_planned_evaluation_periods"
    __table_args__ = (
        CheckConstraint("sequence > 0", name="ck_talent_planned_evaluation_periods_sequence"),
        CheckConstraint("status IN ('planned','cancelled')", name="ck_talent_planned_evaluation_periods_status"),
        CheckConstraint("planned_start_date IS NULL OR planned_end_date IS NULL OR planned_start_date <= planned_end_date", name="ck_talent_planned_evaluation_periods_dates"),
        CheckConstraint("(status = 'planned' AND cancellation_reason IS NULL AND cancelled_at IS NULL AND cancelled_by_user_id IS NULL) OR (status = 'cancelled' AND cancellation_reason IS NOT NULL AND cancelled_at IS NOT NULL)", name="ck_talent_planned_evaluation_periods_cancellation"),
        ForeignKeyConstraint(
            ["annual_evaluation_plan_id", "program_id", "academic_year_id", "school_group_id"],
            ["talent_annual_evaluation_plans.id", "talent_annual_evaluation_plans.program_id", "talent_annual_evaluation_plans.academic_year_id", "talent_annual_evaluation_plans.school_group_id"],
            name="fk_talent_planned_evaluation_periods_plan_scope",
        ),
        UniqueConstraint("annual_evaluation_plan_id", "sequence", name="uq_talent_planned_evaluation_periods_sequence"),
        UniqueConstraint("annual_evaluation_plan_id", "normalized_label", name="uq_talent_planned_evaluation_periods_label"),
        UniqueConstraint("annual_evaluation_plan_id", "normalized_short_code", name="uq_talent_planned_evaluation_periods_code"),
        UniqueConstraint("id", "program_id", "academic_year_id", "school_group_id", name="uq_talent_planned_evaluation_periods_cycle_scope"),
        Index("ix_talent_planned_evaluation_periods_plan", "school_group_id", "annual_evaluation_plan_id", "sequence"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    program_id = Column(Integer, nullable=False)
    academic_year_id = Column(Integer, nullable=False)
    annual_evaluation_plan_id = Column(Integer, nullable=False)
    sequence = Column(Integer, nullable=False)
    label = Column(String(160), nullable=False)
    normalized_label = Column(String(160), nullable=False)
    short_code = Column(String(40), nullable=True)
    normalized_short_code = Column(String(40), nullable=True)
    planned_start_date = Column(Date, nullable=True)
    planned_end_date = Column(Date, nullable=True)
    is_required = Column(Boolean, nullable=False, default=True)
    status = Column(String(16), nullable=False, default="planned")
    notes = Column(String(1000), nullable=True)
    cancellation_reason = Column(String(500), nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TalentAssessmentCycle(Base):
    __tablename__ = "talent_assessment_cycles"
    __table_args__ = (
        CheckConstraint("status IN ('draft','open','closed')", name="ck_talent_assessment_cycles_status"),
        CheckConstraint("revision >= 1", name="ck_talent_assessment_cycles_revision"),
        CheckConstraint("population_count IS NULL OR population_count >= 0", name="ck_talent_assessment_cycles_population_count"),
        ForeignKeyConstraint(["program_id", "school_group_id"], ["talent_programs.id", "talent_programs.school_group_id"], name="fk_talent_assessment_cycles_program_scope"),
        ForeignKeyConstraint(["academic_year_id", "school_group_id"], ["academic_years.id", "academic_years.school_group_id"], name="fk_talent_assessment_cycles_year_scope"),
        ForeignKeyConstraint(["framework_version_id", "program_id", "school_group_id"], ["talent_program_framework_versions.id", "talent_program_framework_versions.program_id", "talent_program_framework_versions.school_group_id"], name="fk_talent_assessment_cycles_framework_scope"),
        ForeignKeyConstraint(["planned_evaluation_period_id", "program_id", "academic_year_id", "school_group_id"], ["talent_planned_evaluation_periods.id", "talent_planned_evaluation_periods.program_id", "talent_planned_evaluation_periods.academic_year_id", "talent_planned_evaluation_periods.school_group_id"], name="fk_talent_assessment_cycles_period_scope"),
        UniqueConstraint("planned_evaluation_period_id", name="uq_talent_assessment_cycles_period"),
        UniqueConstraint("id", "program_id", "academic_year_id", "framework_version_id", "school_group_id", name="uq_talent_assessment_cycles_frozen_scope"),
        Index("ix_talent_assessment_cycles_scope", "school_group_id", "program_id", "academic_year_id", "status"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    program_id = Column(Integer, nullable=False)
    academic_year_id = Column(Integer, nullable=False)
    framework_version_id = Column(Integer, nullable=False)
    planned_evaluation_period_id = Column(Integer, nullable=True)
    title = Column(String(180), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="draft")
    revision = Column(Integer, nullable=False, default=1)
    population_effective_at = Column(DateTime, nullable=True)
    population_count = Column(Integer, nullable=True)
    population_fingerprint = Column(String(64), nullable=True)
    opened_at = Column(DateTime, nullable=True)
    opened_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    closed_at = Column(DateTime, nullable=True)
    closed_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    updated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TalentAssessmentCyclePopulationMember(Base):
    __tablename__ = "talent_assessment_cycle_population_members"
    __table_args__ = (
        CheckConstraint("grade_level IN ('KG','1','2','3','4','5','6','7','8','9','10','11','12')", name="ck_talent_cycle_population_grade"),
        ForeignKeyConstraint(["cycle_id", "program_id", "academic_year_id", "framework_version_id", "school_group_id"], ["talent_assessment_cycles.id", "talent_assessment_cycles.program_id", "talent_assessment_cycles.academic_year_id", "talent_assessment_cycles.framework_version_id", "talent_assessment_cycles.school_group_id"], name="fk_talent_cycle_population_cycle_scope"),
        ForeignKeyConstraint(["student_id", "school_group_id"], ["students.id", "students.school_group_id"], name="fk_talent_cycle_population_student_scope"),
        ForeignKeyConstraint(["academic_placement_id", "student_id", "academic_year_id", "branch_id", "school_group_id"], ["student_academic_placements.id", "student_academic_placements.student_id", "student_academic_placements.academic_year_id", "student_academic_placements.branch_id", "student_academic_placements.school_group_id"], name="fk_talent_cycle_population_placement_scope"),
        UniqueConstraint("cycle_id", "student_id", name="uq_talent_cycle_population_student"),
        UniqueConstraint("id", "cycle_id", "student_id", "program_id", "academic_year_id", "framework_version_id", "school_group_id", name="uq_talent_cycle_population_member_assessment_scope"),
        Index("ix_talent_cycle_population_scope", "school_group_id", "cycle_id", "branch_id", "student_id"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    cycle_id = Column(Integer, nullable=False)
    program_id = Column(Integer, nullable=False)
    academic_year_id = Column(Integer, nullable=False)
    framework_version_id = Column(Integer, nullable=False)
    student_id = Column(Integer, nullable=False)
    academic_placement_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=False)
    planning_section_id = Column(Integer, ForeignKey("planning_sections.id", ondelete="SET NULL"), nullable=True)
    grade_level = Column(String(8), nullable=False)
    section_name = Column(String(20), nullable=False)
    population_effective_at = Column(DateTime, nullable=False)
    frozen_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TalentStudentAssessment(Base):
    __tablename__ = "talent_student_assessments"
    __table_args__ = (
        CheckConstraint("status IN ('in_progress','completed','incomplete','insufficient_evidence')", name="ck_talent_student_assessments_status"),
        CheckConstraint("revision >= 1", name="ck_talent_student_assessments_revision"),
        ForeignKeyConstraint(
            ["cycle_population_member_id", "cycle_id", "student_id", "program_id", "academic_year_id", "framework_version_id", "school_group_id"],
            ["talent_assessment_cycle_population_members.id", "talent_assessment_cycle_population_members.cycle_id", "talent_assessment_cycle_population_members.student_id", "talent_assessment_cycle_population_members.program_id", "talent_assessment_cycle_population_members.academic_year_id", "talent_assessment_cycle_population_members.framework_version_id", "talent_assessment_cycle_population_members.school_group_id"],
            name="fk_talent_student_assessments_population_scope",
        ),
        UniqueConstraint("cycle_id", "student_id", name="uq_talent_student_assessments_cycle_student"),
        UniqueConstraint("id", "cycle_id", "student_id", "program_id", "academic_year_id", "framework_version_id", "school_group_id", name="uq_talent_student_assessments_result_scope"),
        Index("ix_talent_student_assessments_scope", "school_group_id", "cycle_id", "student_id", "status"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    cycle_id = Column(Integer, nullable=False)
    cycle_population_member_id = Column(Integer, nullable=False)
    student_id = Column(Integer, nullable=False)
    program_id = Column(Integer, nullable=False)
    academic_year_id = Column(Integer, nullable=False)
    framework_version_id = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="in_progress")
    revision = Column(Integer, nullable=False, default=1)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    completed_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    kpi_calculation_method = Column(String(40), nullable=True)
    kpi_result = Column(Integer, nullable=True)
    kpi_result_scale_min = Column(Integer, nullable=True)
    kpi_result_scale_max = Column(Integer, nullable=True)
    kpi_weighted_numerator = Column(Integer, nullable=True)
    kpi_calculation_fingerprint = Column(String(64), nullable=True)
    kpi_calculated_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    updated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TalentStudentCompetencyResult(Base):
    __tablename__ = "talent_student_competency_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assessment_id", "cycle_id", "student_id", "program_id", "academic_year_id", "framework_version_id", "school_group_id"],
            ["talent_student_assessments.id", "talent_student_assessments.cycle_id", "talent_student_assessments.student_id", "talent_student_assessments.program_id", "talent_student_assessments.academic_year_id", "talent_student_assessments.framework_version_id", "talent_student_assessments.school_group_id"],
            name="fk_talent_competency_results_assessment_scope",
        ),
        ForeignKeyConstraint(
            ["framework_competency_id", "framework_version_id", "program_id", "school_group_id"],
            ["talent_framework_competencies.id", "talent_framework_competencies.framework_version_id", "talent_framework_competencies.program_id", "talent_framework_competencies.school_group_id"],
            name="fk_talent_competency_results_framework_competency_scope",
        ),
        ForeignKeyConstraint(
            ["rubric_level_id", "rubric_id", "framework_version_id", "program_id", "school_group_id"],
            ["talent_rubric_levels.id", "talent_rubric_levels.rubric_id", "talent_rubric_levels.framework_version_id", "talent_rubric_levels.program_id", "talent_rubric_levels.school_group_id"],
            name="fk_talent_competency_results_rubric_level_scope",
        ),
        UniqueConstraint("assessment_id", "framework_competency_id", name="uq_talent_competency_results_assessment_competency"),
        Index("ix_talent_competency_results_assessment", "school_group_id", "assessment_id"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    assessment_id = Column(Integer, nullable=False)
    cycle_id = Column(Integer, nullable=False)
    student_id = Column(Integer, nullable=False)
    program_id = Column(Integer, nullable=False)
    academic_year_id = Column(Integer, nullable=False)
    framework_version_id = Column(Integer, nullable=False)
    framework_competency_id = Column(Integer, nullable=False)
    rubric_id = Column(Integer, nullable=False)
    rubric_level_id = Column(Integer, nullable=False)
    evidence = Column(Text, nullable=True)
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    updated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TalentAssessmentAudit(Base):
    __tablename__ = "talent_assessment_audits"
    __table_args__ = (
        # M6 widens this CHECK to add 'review_candidate' (see
        # db_migrations._talent_review_candidate_foundation) and then further to
        # add 'review_candidate_review', 'official_identification', and
        # 'educator_input' (see
        # db_migrations._talent_review_workflow_identification_educator_input_foundation
        # for the accompanying SQLite table-rebuild/PostgreSQL NOT VALID+VALIDATE
        # widening), matching the M3 precedent of widening
        # TalentConfigurationAudit.resource_type in place for an audit table
        # created by an earlier already-applied migration.
        CheckConstraint(
            "resource_type IN ('assessment_cycle','student_assessment','competency_result','review_candidate','review_candidate_review','official_identification','educator_input')",
            name="ck_talent_assessment_audits_resource_type",
        ),
        ForeignKeyConstraint(["cycle_id", "program_id", "academic_year_id", "framework_version_id", "school_group_id"], ["talent_assessment_cycles.id", "talent_assessment_cycles.program_id", "talent_assessment_cycles.academic_year_id", "talent_assessment_cycles.framework_version_id", "talent_assessment_cycles.school_group_id"], name="fk_talent_assessment_audits_cycle_scope"),
        Index("ix_talent_assessment_audits_cycle", "school_group_id", "cycle_id", "created_at"),
    )
    id = Column(Integer, primary_key=True)
    public_id = Column(String(36), nullable=False, default=lambda: str(uuid.uuid4()), unique=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    # M6 relaxes cycle_id/framework_version_id to nullable (migration
    # 20260904_007_talent_review_workflow_identification_educator_input_foundation):
    # every prior resource_type (assessment_cycle/student_assessment/
    # competency_result/review_candidate/review_candidate_review/
    # official_identification) always has a real Cycle+Framework context, but
    # Educator Input's Cycle binding is explicitly OPTIONAL (Decision 8), so an
    # Educator Input audit row with no Cycle context has no Cycle to bind to.
    # The composite FK below is a standard SQL MATCH SIMPLE constraint, so it is
    # simply not enforced whenever cycle_id (or framework_version_id) is NULL.
    cycle_id = Column(Integer, nullable=True)
    program_id = Column(Integer, nullable=False)
    academic_year_id = Column(Integer, nullable=False)
    framework_version_id = Column(Integer, nullable=True)
    assessment_id = Column(Integer, nullable=True)
    cycle_population_member_id = Column(Integer, nullable=True)
    student_id = Column(Integer, nullable=True)
    actor_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    actor_branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)
    resource_type = Column(String(32), nullable=False, default="assessment_cycle")
    resource_id = Column(Integer, nullable=False)
    action = Column(String(40), nullable=False)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)
    correlation_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TalentReviewCandidate(Base):
    """M6 deterministic Review Candidate materialization for a Completed Assessment.

    Evaluated only from `TalentReviewCandidatePolicy`/`TalentReviewCandidateRule`
    (M3) applied to the exact `TalentStudentAssessment` (M5) and its persisted
    Framework KPI result; never recomputed from current mutable state. A row is
    persisted ONLY for a qualifying (policy-satisfied) evaluation - one per
    Assessment (`uq_talent_review_candidates_assessment`).

    A non-qualifying evaluation never creates a candidate entity. Its bounded
    structural outcome may be recorded in `TalentAssessmentAudit`; only this
    qualifying workflow shape exists in the candidate table.

    Review Candidate is NEVER equivalent to, and never automatically produces,
    Official Identification - that remains a separate append-only human
    decision (`TalentOfficialIdentification`) that may only be recorded once
    this candidate's `status` is `reviewed` (M6 Decision 5 - a `pending_review`
    candidate cannot be identified). Review candidate state and identification
    state are structurally separate (different tables, never a shared mutable
    status column) - see M6 Decision 5/14.

    `status` is exactly two states (M6 Decision 2): a new qualifying candidate
    starts `pending_review`; an authorized human (`talent_review_candidates.manage`)
    may transition it to `reviewed` exactly once - there is no reverse
    transition and no other state (no `dismissed`/`rejected`/`reopened`/
    `escalated`). Marking a candidate `reviewed` never alters assessment
    evidence/competency results/KPI and never automatically identifies the
    Student.
    """

    __tablename__ = "talent_review_candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assessment_id", "cycle_id", "student_id", "program_id", "academic_year_id", "framework_version_id", "school_group_id"],
            ["talent_student_assessments.id", "talent_student_assessments.cycle_id", "talent_student_assessments.student_id", "talent_student_assessments.program_id", "talent_student_assessments.academic_year_id", "talent_student_assessments.framework_version_id", "talent_student_assessments.school_group_id"],
            name="fk_talent_review_candidates_assessment_scope",
        ),
        ForeignKeyConstraint(
            ["cycle_population_member_id", "cycle_id", "student_id", "program_id", "academic_year_id", "framework_version_id", "school_group_id"],
            ["talent_assessment_cycle_population_members.id", "talent_assessment_cycle_population_members.cycle_id", "talent_assessment_cycle_population_members.student_id", "talent_assessment_cycle_population_members.program_id", "talent_assessment_cycle_population_members.academic_year_id", "talent_assessment_cycle_population_members.framework_version_id", "talent_assessment_cycle_population_members.school_group_id"],
            name="fk_talent_review_candidates_population_scope",
        ),
        ForeignKeyConstraint(
            ["policy_id", "framework_version_id", "program_id", "school_group_id"],
            ["talent_review_candidate_policies.id", "talent_review_candidate_policies.framework_version_id", "talent_review_candidate_policies.program_id", "talent_review_candidate_policies.school_group_id"],
            name="fk_talent_review_candidates_policy_scope",
        ),
        CheckConstraint("match_mode IN ('all','any')", name="ck_talent_review_candidates_mode"),
        CheckConstraint("status IN ('pending_review','reviewed')", name="ck_talent_review_candidates_status"),
        UniqueConstraint("assessment_id", name="uq_talent_review_candidates_assessment"),
        UniqueConstraint("id", "assessment_id", "cycle_id", "cycle_population_member_id", "student_id", "program_id", "academic_year_id", "framework_version_id", "school_group_id", name="uq_talent_review_candidates_identification_scope"),
        Index("ix_talent_review_candidates_scope", "school_group_id", "cycle_id", "student_id"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    cycle_id = Column(Integer, nullable=False)
    cycle_population_member_id = Column(Integer, nullable=False)
    student_id = Column(Integer, nullable=False)
    program_id = Column(Integer, nullable=False)
    academic_year_id = Column(Integer, nullable=False)
    framework_version_id = Column(Integer, nullable=False)
    assessment_id = Column(Integer, nullable=False)
    policy_id = Column(Integer, nullable=False)
    match_mode = Column(String(8), nullable=False)
    evaluation_fingerprint = Column(String(64), nullable=False)
    evaluation_snapshot_json = Column(Text, nullable=False)
    evaluated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    evaluated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    status = Column(String(16), nullable=False, default="pending_review", server_default=text("'pending_review'"))
    reviewed_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)


class TalentOfficialIdentification(Base):
    """M6 append-only human Official Identification decision (Decisions 3-7, 17).

    Exactly one decision (`identified`/`not_identified`) may ever be recorded
    per qualifying `TalentReviewCandidate` (`uq_talent_official_identifications_candidate`
    - structurally enforced, not merely service-checked). `decision` is durable
    and history-bearing either way: `not_identified` is a real, final, human
    governance outcome, never a failed-assessment/failed-KPI/low-score signal,
    and is never deleted or silently overwritten (Decision 4). There is no
    mutation, revocation, supersession, second decision, or re-identification
    path anywhere in this model or its service (Decision 17 - explicitly
    deferred, not implemented).

    Binds to the exact same upstream chain as the `TalentReviewCandidate` it
    decides (SchoolGroup, Student, Program, AcademicYear, Cycle, frozen Cycle
    Population Member, Completed Assessment, exact Framework Version) using
    the identical composite-scoped-FK pattern `TalentReviewCandidate` itself
    uses, plus a direct FK to the Review Candidate row.
    """

    __tablename__ = "talent_official_identifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assessment_id", "cycle_id", "student_id", "program_id", "academic_year_id", "framework_version_id", "school_group_id"],
            ["talent_student_assessments.id", "talent_student_assessments.cycle_id", "talent_student_assessments.student_id", "talent_student_assessments.program_id", "talent_student_assessments.academic_year_id", "talent_student_assessments.framework_version_id", "talent_student_assessments.school_group_id"],
            name="fk_talent_official_identifications_assessment_scope",
        ),
        ForeignKeyConstraint(
            ["cycle_population_member_id", "cycle_id", "student_id", "program_id", "academic_year_id", "framework_version_id", "school_group_id"],
            ["talent_assessment_cycle_population_members.id", "talent_assessment_cycle_population_members.cycle_id", "talent_assessment_cycle_population_members.student_id", "talent_assessment_cycle_population_members.program_id", "talent_assessment_cycle_population_members.academic_year_id", "talent_assessment_cycle_population_members.framework_version_id", "talent_assessment_cycle_population_members.school_group_id"],
            name="fk_talent_official_identifications_population_scope",
        ),
        ForeignKeyConstraint(
            ["review_candidate_id", "assessment_id", "cycle_id", "cycle_population_member_id", "student_id", "program_id", "academic_year_id", "framework_version_id", "school_group_id"],
            ["talent_review_candidates.id", "talent_review_candidates.assessment_id", "talent_review_candidates.cycle_id", "talent_review_candidates.cycle_population_member_id", "talent_review_candidates.student_id", "talent_review_candidates.program_id", "talent_review_candidates.academic_year_id", "talent_review_candidates.framework_version_id", "talent_review_candidates.school_group_id"],
            name="fk_talent_official_identifications_candidate_scope",
        ),
        CheckConstraint("decision IN ('identified','not_identified')", name="ck_talent_official_identifications_decision"),
        UniqueConstraint("review_candidate_id", name="uq_talent_official_identifications_candidate"),
        Index("ix_talent_official_identifications_scope", "school_group_id", "cycle_id", "student_id"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    cycle_id = Column(Integer, nullable=False)
    cycle_population_member_id = Column(Integer, nullable=False)
    student_id = Column(Integer, nullable=False)
    program_id = Column(Integer, nullable=False)
    academic_year_id = Column(Integer, nullable=False)
    framework_version_id = Column(Integer, nullable=False)
    assessment_id = Column(Integer, nullable=False)
    review_candidate_id = Column(Integer, nullable=False)
    decision = Column(String(16), nullable=False)
    rationale = Column(Text, nullable=True)
    decided_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    decided_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TalentEducatorInput(Base):
    """M6 bounded qualitative Educator Input evidence/context (Decisions 8-13).

    Explicitly NOT a generic note, private diary, assessment score, Official
    Identification, Review Candidate state, AI output, or messaging/chat.

    Required binding: SchoolGroup, Student, Program, AcademicYear,
    `observed_at`, and historical Academic Placement/Branch context
    (`academic_placement_id`/`branch_id`/`grade_level`/`section_name`, frozen
    at input-creation time exactly like `TalentAssessmentCyclePopulationMember`
    freezes Branch/Grade/Section at Cycle-Open time - see
    `talent_educator_input_service.py` for the resolution rule: if no frozen
    Cycle context is supplied, the Student's canonical
    `StudentAcademicPlacement` effective AT `observed_at` within the specified
    AcademicYear is resolved and snapshotted; a Student with no valid
    historical Placement at that instant is rejected rather than silently
    falling back to current Placement).

    Optional binding: Cycle, frozen Cycle Population Member, Assessment,
    Review Candidate - when supplied, the service validates exact Student/
    Program/AcademicYear alignment rather than trusting the caller, and the
    historical Placement/Branch snapshot is taken from that frozen Cycle
    Population Member instead of being independently re-resolved.

    `category` is a closed enum (`observation`/`context`/`supporting_evidence`)
    - purely descriptive metadata that never changes deterministic assessment/
    identification state. `content` is plain bounded text (see
    `talent_educator_input_service.MAX_CONTENT_LENGTH`) - no HTML/Markdown
    execution, attachments, files, or arbitrary JSON.

    Append-only with amendment/supersession lineage via the self-referential,
    nullable `supersedes_educator_input_id` - the original row is never edited
    in place or hard-deleted; an amendment is a new row referencing the row it
    supersedes (cycle-prevention and cross-Student/Program/tenant validation
    live in the service, mirroring M3's `_validate_supersedes` Framework
    Version supersession pattern).
    """

    __tablename__ = "talent_educator_inputs"
    __table_args__ = (
        ForeignKeyConstraint(["student_id", "school_group_id"], ["students.id", "students.school_group_id"], name="fk_talent_educator_inputs_student_scope"),
        ForeignKeyConstraint(["program_id", "school_group_id"], ["talent_programs.id", "talent_programs.school_group_id"], name="fk_talent_educator_inputs_program_scope"),
        ForeignKeyConstraint(["academic_year_id", "school_group_id"], ["academic_years.id", "academic_years.school_group_id"], name="fk_talent_educator_inputs_year_scope"),
        ForeignKeyConstraint(["branch_id", "school_group_id"], ["branches.id", "branches.school_group_id"], name="fk_talent_educator_inputs_branch_scope"),
        ForeignKeyConstraint(
            ["academic_placement_id", "student_id", "academic_year_id", "branch_id", "school_group_id"],
            ["student_academic_placements.id", "student_academic_placements.student_id", "student_academic_placements.academic_year_id", "student_academic_placements.branch_id", "student_academic_placements.school_group_id"],
            name="fk_talent_educator_inputs_placement_scope",
        ),
        CheckConstraint("grade_level IN ('KG','1','2','3','4','5','6','7','8','9','10','11','12')", name="ck_talent_educator_inputs_grade"),
        CheckConstraint("category IN ('observation','context','supporting_evidence')", name="ck_talent_educator_inputs_category"),
        UniqueConstraint("id", "student_id", "program_id", "academic_year_id", "school_group_id", name="uq_talent_educator_inputs_lineage_scope"),
        UniqueConstraint("supersedes_educator_input_id", name="uq_talent_educator_inputs_superseded_once"),
        ForeignKeyConstraint(
            ["supersedes_educator_input_id", "student_id", "program_id", "academic_year_id", "school_group_id"],
            ["talent_educator_inputs.id", "talent_educator_inputs.student_id", "talent_educator_inputs.program_id", "talent_educator_inputs.academic_year_id", "talent_educator_inputs.school_group_id"],
            name="fk_talent_educator_inputs_supersession_scope",
        ),
        Index("ix_talent_educator_inputs_scope", "school_group_id", "student_id", "program_id", "academic_year_id"),
        Index("ix_talent_educator_inputs_lineage", "supersedes_educator_input_id"),
    )
    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    student_id = Column(Integer, nullable=False)
    program_id = Column(Integer, nullable=False)
    academic_year_id = Column(Integer, nullable=False)
    observed_at = Column(DateTime, nullable=False)
    academic_placement_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=False)
    planning_section_id = Column(Integer, ForeignKey("planning_sections.id", ondelete="SET NULL"), nullable=True)
    grade_level = Column(String(8), nullable=False)
    section_name = Column(String(20), nullable=False)
    cycle_id = Column(Integer, ForeignKey("talent_assessment_cycles.id"), nullable=True)
    cycle_population_member_id = Column(Integer, ForeignKey("talent_assessment_cycle_population_members.id"), nullable=True)
    assessment_id = Column(Integer, ForeignKey("talent_student_assessments.id"), nullable=True)
    review_candidate_id = Column(Integer, ForeignKey("talent_review_candidates.id"), nullable=True)
    category = Column(String(24), nullable=False)
    content = Column(Text, nullable=False)
    supersedes_educator_input_id = Column(Integer, nullable=True)
    author_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index(
            "uq_users_email_normalized",
            "email_normalized",
            unique=True,
            sqlite_where=text("email_normalized IS NOT NULL"),
            postgresql_where=text("email_normalized IS NOT NULL"),
        ),
        Index("ix_users_internal_test_identity", "is_internal_test_identity"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(String(10), unique=True, index=True)
    username = Column(String(50), unique=True, index=True)
    email = Column(String(180), unique=True, index=True)
    email_normalized = Column(String(180))
    email_verified_at = Column(DateTime)
    first_name = Column(String)
    last_name = Column(String)
    position = Column(String(50))
    password = Column(String)
    role = Column(String)
    user_type = Column(String(20), nullable=False, default="TENANT", index=True)
    platform_role = Column(String(40), index=True)
    platform_owner_kind = Column(String(20), index=True)
    platform_permissions_initialized = Column(Boolean, nullable=False, default=False)
    access_scope = Column(String(20), nullable=False, default="BRANCH", index=True)
    profile_image_path = Column(String(255))
    profile_image_content_type = Column(String(50))
    profile_image_data = Column(LargeBinary)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"))
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"))
    is_active = Column(Boolean, default=True)
    is_internal_test_identity = Column(Boolean, nullable=False, default=False)
    last_login_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PlatformUserPermission(Base):
    __tablename__ = "platform_user_permissions"
    __table_args__ = (
        UniqueConstraint(
            "platform_user_id",
            "permission_key",
            name="uq_platform_user_permissions_user_key",
        ),
        Index("ix_platform_user_permissions_user", "platform_user_id"),
    )

    id = Column(Integer, primary_key=True)
    platform_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    permission_key = Column(String(120), nullable=False, index=True)
    is_allowed = Column(Boolean, nullable=False, default=True)
    updated_by_user_id = Column(String(10))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SystemNotification(Base):
    __tablename__ = "system_notifications"
    __table_args__ = (
        Index("ix_system_notifications_recipient_status", "recipient_user_id", "status"),
        Index("ix_system_notifications_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), index=True)
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"), index=True)
    recipient_user_id = Column(String(10), index=True, nullable=False)
    requesting_user_id = Column(String(10), index=True)
    request_type = Column(String(80), nullable=False)
    title = Column(String(160), nullable=False)
    message = Column(Text)
    details = Column(Text)
    status = Column(String(20), nullable=False, default="New")
    recipient_scope = Column(String(10), nullable=False, default="User")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    seen_at = Column(DateTime)
    resolved_at = Column(DateTime)
    resolved_by_user_id = Column(String(10))
    recipient_archived_at = Column(DateTime)
    recipient_archived_by_user_id = Column(String(10))
    requester_archived_at = Column(DateTime)
    requester_archived_by_user_id = Column(String(10))
    destination_url = Column(String(500))
    deduplication_key = Column(String(180), unique=True, index=True)
    category = Column(String(40))
    severity = Column(String(20))


class DemoRequest(Base):
    __tablename__ = "demo_requests"
    __table_args__ = (
        Index("ix_demo_requests_submitted_at", "submitted_at"),
        Index("ix_demo_requests_status", "status"),
        Index("ix_demo_requests_interested_plan", "interested_plan"),
        Index("ix_demo_requests_email", "email"),
    )

    id = Column(Integer, primary_key=True)
    submitted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    school_name = Column(String(180), nullable=False, default="")
    full_name = Column(String(160), nullable=False, default="")
    email = Column(String(180), nullable=False, default="")
    phone = Column(String(80), nullable=False, default="")
    country = Column(String(120), nullable=False, default="")
    school_type = Column(String(120), nullable=False, default="")
    number_of_teachers = Column(String(40), nullable=False, default="")
    number_of_students = Column(String(40), nullable=False, default="")
    number_of_branches = Column(String(40), nullable=False, default="")
    interested_plan = Column(String(80), nullable=False, default="")
    message = Column(Text, nullable=False, default="")
    status = Column(String(40), nullable=False, default="New")
    source_host = Column(String(180), nullable=False, default="")
    source_ip = Column(String(80), nullable=False, default="")
    status_updated_at = Column(DateTime)
    status_updated_by_user_id = Column(String(10))
    seen_at = Column(DateTime)
    seen_by_user_id = Column(String(10))


class CalendarEventType(Base):
    __tablename__ = "calendar_event_types"
    __table_args__ = (
        UniqueConstraint(
            "branch_id",
            "academic_year_id",
            "name",
            name="uq_calendar_event_types_scope_name",
        ),
        Index("ix_calendar_event_types_scope", "branch_id", "academic_year_id"),
    )

    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    academic_year_id = Column(
        Integer,
        ForeignKey("academic_years.id"),
        nullable=False,
        index=True,
    )
    name = Column(String(120), nullable=False)
    color = Column(String(7), nullable=False, default="#0A4EA3")
    icon = Column(String(80), nullable=False, default="year")
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        Index("ix_calendar_events_scope_date", "branch_id", "academic_year_id", "event_date"),
        Index("ix_calendar_events_type", "event_type_id"),
        Index("ix_calendar_events_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    academic_year_id = Column(
        Integer,
        ForeignKey("academic_years.id"),
        nullable=False,
        index=True,
    )
    event_type_id = Column(Integer, ForeignKey("calendar_event_types.id"), index=True)
    title = Column(String(180), nullable=False)
    event_date = Column(String(10), nullable=False, index=True)
    end_date = Column(String(10), index=True)
    start_time = Column(String(5))
    end_time = Column(String(5))
    all_day = Column(Boolean, nullable=False, default=False)
    description = Column(Text)
    target_group = Column(String(40), nullable=False, default="All School")
    target_grade = Column(String(20))
    target_section_id = Column(Integer, ForeignKey("planning_sections.id"))
    target_teacher_id = Column(Integer, ForeignKey("teachers.id"))
    target_role = Column(String(80))
    priority = Column(String(20), nullable=False, default="Normal")
    status = Column(String(20), nullable=False, default="Planned")
    recurrence_rule = Column(String(40), nullable=False, default="None")
    recurrence_interval = Column(Integer, nullable=False, default=1)
    recurrence_until = Column(String(10))
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"))
    updated_by_user_id = Column(String(10), ForeignKey("users.user_id"))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CalendarEventAssignment(Base):
    __tablename__ = "calendar_event_assignments"
    __table_args__ = (
        Index("ix_calendar_event_assignments_event", "calendar_event_id"),
        Index("ix_calendar_event_assignments_teacher", "teacher_id"),
        Index("ix_calendar_event_assignments_user", "user_id"),
    )

    id = Column(Integer, primary_key=True)
    calendar_event_id = Column(
        Integer,
        ForeignKey("calendar_events.id"),
        nullable=False,
        index=True,
    )
    teacher_id = Column(Integer, ForeignKey("teachers.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    assignment_role = Column(String(80))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CalendarEventGradeTarget(Base):
    __tablename__ = "calendar_event_grade_targets"
    __table_args__ = (
        UniqueConstraint(
            "calendar_event_id",
            "grade_level",
            name="uq_calendar_event_grade_targets_event_grade",
        ),
        Index("ix_calendar_event_grade_targets_event", "calendar_event_id"),
        Index("ix_calendar_event_grade_targets_grade", "grade_level"),
    )

    id = Column(Integer, primary_key=True)
    calendar_event_id = Column(
        Integer,
        ForeignKey("calendar_events.id"),
        nullable=False,
        index=True,
    )
    grade_level = Column(String(20), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CalendarEventSectionTarget(Base):
    __tablename__ = "calendar_event_section_targets"
    __table_args__ = (
        UniqueConstraint(
            "calendar_event_id",
            "section_id",
            name="uq_calendar_event_section_targets_event_section",
        ),
        Index("ix_calendar_event_section_targets_event", "calendar_event_id"),
        Index("ix_calendar_event_section_targets_section", "section_id"),
    )

    id = Column(Integer, primary_key=True)
    calendar_event_id = Column(
        Integer,
        ForeignKey("calendar_events.id"),
        nullable=False,
        index=True,
    )
    section_id = Column(Integer, ForeignKey("planning_sections.id"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CalendarEventNotification(Base):
    __tablename__ = "calendar_event_notifications"
    __table_args__ = (
        Index("ix_calendar_event_notifications_event", "calendar_event_id"),
        Index("ix_calendar_event_notifications_notification", "system_notification_id"),
    )

    id = Column(Integer, primary_key=True)
    calendar_event_id = Column(
        Integer,
        ForeignKey("calendar_events.id"),
        nullable=False,
        index=True,
    )
    assignment_id = Column(Integer, ForeignKey("calendar_event_assignments.id"))
    system_notification_id = Column(Integer, ForeignKey("system_notifications.id"))
    notification_kind = Column(String(40), nullable=False, default="Assigned")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (
        Index(
            "uq_subjects_scope_code",
            "branch_id",
            "academic_year_id",
            "subject_code",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    subject_code = Column(String, index=True)
    subject_name = Column(String)
    color = Column(String(7))
    weekly_hours = Column(Integer)
    grade = Column(Integer)
    branch_id = Column(Integer, ForeignKey("branches.id"))
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"))


class Teacher(Base):
    __tablename__ = "teachers"
    __table_args__ = (
        UniqueConstraint(
            "id", "branch_id", "academic_year_id",
            name="uq_teachers_id_scope",
        ),
        Index(
            "uq_teachers_scope_teacher_id",
            "branch_id",
            "academic_year_id",
            "teacher_id",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    teacher_id = Column(String(10))
    first_name = Column(String)
    middle_name = Column(String)
    last_name = Column(String)
    degree_major = Column(String(120))
    # Stored as a scoped legacy value; validation is enforced in the app layer.
    subject_code = Column(String)
    level = Column(String)
    max_hours = Column(Integer, default=24)
    extra_hours_allowed = Column(Boolean, default=False)
    extra_hours_count = Column(Integer, default=0)
    teaches_national_section = Column(Boolean, default=False)
    national_section_hours = Column(Integer, default=0)
    is_new_teacher = Column(Boolean, default=False)
    branch_id = Column(Integer, ForeignKey("branches.id"))
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"))


class TeacherSubjectAllocation(Base):
    __tablename__ = "teacher_subject_allocations"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id",
            "subject_code",
            name="uq_teacher_subject_allocations_teacher_subject",
        ),
    )

    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False, index=True)
    # Subject codes are branch/year scoped, so allocations store the selected code
    # and resolve it through the teacher's current scope.
    subject_code = Column(String, nullable=False)
    compatibility_override = Column(Boolean, default=False, nullable=False)


class TeacherQualificationSelection(Base):
    __tablename__ = "teacher_qualification_selections"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id",
            "qualification_key",
            name="uq_teacher_qualification_selections_teacher_qualification",
        ),
    )

    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False, index=True)
    qualification_key = Column(String(80), nullable=False)


class QualificationOption(Base):
    __tablename__ = "qualification_options"
    __table_args__ = (
        UniqueConstraint(
            "qualification_key",
            name="uq_qualification_options_key",
        ),
    )

    id = Column(Integer, primary_key=True)
    qualification_key = Column(String(80), nullable=False, index=True)
    label = Column(String(120), nullable=False)
    kind = Column(String(32), nullable=False)
    alignment_keys = Column(String(255), nullable=False, default="")
    legacy_aliases = Column(String(500), nullable=False, default="")
    sort_order = Column(Integer, nullable=False, default=0)


class TeacherSectionAssignment(Base):
    __tablename__ = "teacher_section_assignments"
    __table_args__ = (
        UniqueConstraint(
            "planning_section_id",
            "subject_code",
            name="uq_teacher_section_assignments_section_subject",
        ),
        Index(
            "ix_teacher_section_assignments_teacher_id",
            "teacher_id",
        ),
        Index(
            "ix_teacher_section_assignments_planning_section_id",
            "planning_section_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    planning_section_id = Column(
        Integer,
        ForeignKey("planning_sections.id"),
        nullable=False,
    )
    subject_code = Column(String, nullable=False)


class ObservationCriterion(Base):
    __tablename__ = "observation_criteria"
    __table_args__ = (
        UniqueConstraint(
            "domain_key",
            "indicator_number",
            name="uq_observation_criteria_domain_indicator",
        ),
        Index("ix_observation_criteria_sort", "sort_order"),
    )

    id = Column(Integer, primary_key=True)
    domain_key = Column(String(8), nullable=False)
    domain_title = Column(String(160), nullable=False)
    indicator_number = Column(Integer, nullable=False)
    title = Column(Text, nullable=False)
    guidelines = Column(Text, nullable=False, default="")
    evidence_examples = Column(Text, nullable=False, default="")
    rubric_descriptors = Column(Text, nullable=False, default="{}")
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        Index("ix_observations_teacher_scope", "teacher_id", "branch_id", "academic_year_id"),
        Index("ix_observations_type_status", "observation_type", "status"),
        Index("ix_observations_date", "observation_date"),
    )

    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"), nullable=False, index=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False, index=True)
    evaluator_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=False, index=True)
    observation_type = Column(String(20), nullable=False, default="Formal")
    observation_date = Column(String(10), nullable=False)
    term = Column(String(20))
    grade = Column(String(20))
    section = Column(String(20))
    period = Column(String(20))
    subject = Column(String(120))
    status = Column(String(20), nullable=False, default="Final")
    overall_score = Column(String(20))
    evaluator_notes = Column(Text)
    evaluatee_notes = Column(Text)
    teacher_signature_data = Column(Text)
    evaluator_signature_data = Column(Text)
    locked_at = Column(DateTime)
    smart_feedback = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ObservationScore(Base):
    __tablename__ = "observation_scores"
    __table_args__ = (
        UniqueConstraint(
            "observation_id",
            "criterion_id",
            name="uq_observation_scores_observation_criterion",
        ),
        Index("ix_observation_scores_observation", "observation_id"),
    )

    id = Column(Integer, primary_key=True)
    observation_id = Column(Integer, ForeignKey("observations.id"), nullable=False, index=True)
    criterion_id = Column(Integer, ForeignKey("observation_criteria.id"), nullable=False, index=True)
    rating = Column(String(4), nullable=False, default="NA")
    evidence = Column(Text)


class ObservationSelfEvaluation(Base):
    __tablename__ = "observation_self_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "observation_id",
            "teacher_id",
            name="uq_observation_self_evaluations_observation_teacher",
        ),
        Index("ix_observation_self_evaluations_observation", "observation_id"),
    )

    id = Column(Integer, primary_key=True)
    observation_id = Column(Integer, ForeignKey("observations.id"), nullable=False, index=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False, index=True)
    reflection = Column(Text)
    strengths = Column(Text)
    growth_areas = Column(Text)
    support_needed = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ObservationSelfEvaluationScore(Base):
    __tablename__ = "observation_self_evaluation_scores"
    __table_args__ = (
        UniqueConstraint(
            "self_evaluation_id",
            "criterion_id",
            name="uq_observation_self_eval_scores_eval_criterion",
        ),
        Index("ix_observation_self_eval_scores_eval", "self_evaluation_id"),
    )

    id = Column(Integer, primary_key=True)
    self_evaluation_id = Column(Integer, ForeignKey("observation_self_evaluations.id"), nullable=False, index=True)
    criterion_id = Column(Integer, ForeignKey("observation_criteria.id"), nullable=False, index=True)
    rating = Column(String(4), nullable=False, default="NA")
    evidence = Column(Text)


class PlanningSection(Base):
    __tablename__ = "planning_sections"
    __table_args__ = (
        UniqueConstraint(
            "grade_level",
            "section_name",
            "branch_id",
            "academic_year_id",
            name="uq_planning_sections_scope_grade_section",
        ),
        UniqueConstraint(
            "id",
            "branch_id",
            "academic_year_id",
            name="uq_planning_sections_id_scope",
        ),
    )

    id = Column(Integer, primary_key=True)
    grade_level = Column(String(8), nullable=False)
    section_name = Column(String(20), nullable=False)
    class_status = Column(String(20), nullable=False)
    homeroom_teacher_id = Column(Integer, nullable=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"), nullable=False)


class PlanningSubjectDemand(Base):
    """Explicit section-subject weekly demand introduced alongside legacy Planning.

    Stage 1 records are additive. Existing operational consumers continue deriving
    demand from Subject grade/weekly_hours until a later migration of authority.
    """

    __tablename__ = "planning_subject_demands"
    __table_args__ = (
        CheckConstraint(
            "weekly_periods >= 0",
            name="ck_planning_subject_demands_weekly_periods_nonnegative",
        ),
        ForeignKeyConstraint(
            ["planning_section_id", "branch_id", "academic_year_id"],
            [
                "planning_sections.id",
                "planning_sections.branch_id",
                "planning_sections.academic_year_id",
            ],
            name="fk_planning_subject_demands_section_scope",
        ),
        ForeignKeyConstraint(
            ["branch_id", "academic_year_id", "subject_code"],
            ["subjects.branch_id", "subjects.academic_year_id", "subjects.subject_code"],
            name="fk_planning_subject_demands_subject_scope",
        ),
        Index(
            "uq_planning_subject_demands_active_section_subject",
            "planning_section_id",
            "subject_code",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active = true"),
        ),
        Index(
            "ix_planning_subject_demands_scope",
            "branch_id",
            "academic_year_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"), nullable=False)
    planning_section_id = Column(Integer, nullable=False)
    subject_code = Column(String, nullable=False)
    weekly_periods = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    retired_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    updated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)


class CurriculumAdjustmentAudit(Base):
    __tablename__ = "curriculum_adjustment_audits"
    __table_args__ = (
        CheckConstraint(
            "status IN ('applied')",
            name="ck_curriculum_adjustment_audits_status",
        ),
        UniqueConstraint(
            "school_group_id", "branch_id", "academic_year_id", "preview_fingerprint",
            name="uq_curriculum_adjustment_audits_scope_preview",
        ),
        Index(
            "ix_curriculum_adjustment_audits_scope_created",
            "school_group_id", "branch_id", "academic_year_id", "created_at",
        ),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(String(36), nullable=False, default=lambda: str(uuid.uuid4()), unique=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"), nullable=False)
    actor_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=False)
    scope_type = Column(String(32), nullable=False)
    source_subject_code = Column(String, nullable=False)
    target_subject_code = Column(String, nullable=False)
    preview_fingerprint = Column(String(64), nullable=False)
    request_json = Column(Text, nullable=False)
    per_section_json = Column(Text, nullable=False)
    warnings_json = Column(Text, nullable=False, default="[]")
    status = Column(String(16), nullable=False, default="applied")
    draft_version_id = Column(Integer, ForeignKey("timetable_versions.id"), nullable=True)
    draft_marked_stale = Column(Boolean, nullable=False, default=False)
    regeneration_required = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TimetableSetting(Base):
    __tablename__ = "timetable_settings"
    __table_args__ = (
        UniqueConstraint(
            "branch_id",
            "academic_year_id",
            name="uq_timetable_settings_scope",
        ),
    )

    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    academic_year_id = Column(
        Integer,
        ForeignKey("academic_years.id"),
        nullable=False,
        index=True,
    )
    working_days_csv = Column(String(120), nullable=False, default="")
    periods_per_day = Column(Integer, nullable=False, default=8)
    period_duration_minutes = Column(Integer, nullable=False, default=45)
    school_start_time = Column(String(5), nullable=False, default="07:00")
    school_end_time = Column(String(5), nullable=False, default="13:00")
    quality_rules_json = Column(Text, nullable=False, default="{}")


class TimetableNonTeachingBlock(Base):
    __tablename__ = "timetable_non_teaching_blocks"
    __table_args__ = (
        Index(
            "ix_timetable_non_teaching_blocks_setting_id",
            "timetable_setting_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    timetable_setting_id = Column(
        Integer,
        ForeignKey("timetable_settings.id"),
        nullable=False,
    )
    block_type = Column(String(32), nullable=False)
    label = Column(String(80), nullable=False)
    day_key = Column(String(16), nullable=False, default="all")
    start_time = Column(String(5), nullable=True)
    end_time = Column(String(5), nullable=True)
    start_period = Column(Integer, nullable=False)
    end_period = Column(Integer, nullable=False)
    placement_mode = Column(String(24), nullable=False, default="fixed_time")
    insert_after_period = Column(Integer, nullable=True)
    duration_minutes = Column(Integer, nullable=True)


class TeacherSchedulingRule(Base):
    __tablename__ = "teacher_scheduling_rules"
    __table_args__ = (
        CheckConstraint(
            "rule_type IN ('must_teach','unavailable','prefer_teaching','prefer_free')",
            name="ck_teacher_scheduling_rules_type",
        ),
        CheckConstraint(
            "target_scope IN ('any_assigned','selected_grades','selected_sections')",
            name="ck_teacher_scheduling_rules_target_scope",
        ),
        CheckConstraint(
            "(rule_type IN ('must_teach','unavailable') AND strictness = 'hard') OR "
            "(rule_type IN ('prefer_teaching','prefer_free') AND strictness = 'soft')",
            name="ck_teacher_scheduling_rules_semantics",
        ),
        ForeignKeyConstraint(
            ["teacher_id", "branch_id", "academic_year_id"],
            ["teachers.id", "teachers.branch_id", "teachers.academic_year_id"],
            name="fk_teacher_scheduling_rules_teacher_scope",
        ),
        Index(
            "ix_teacher_scheduling_rules_scope_teacher",
            "school_group_id", "branch_id", "academic_year_id", "teacher_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"), nullable=False)
    teacher_id = Column(Integer, nullable=False)
    rule_type = Column(String(24), nullable=False)
    restrict_to_window = Column(Boolean, nullable=False, default=False)
    target_scope = Column(String(24), nullable=False, default="any_assigned")
    strictness = Column(String(8), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    updated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TeacherSchedulingRuleSlot(Base):
    __tablename__ = "teacher_scheduling_rule_slots"
    __table_args__ = (
        CheckConstraint(
            "period_selector IN ('period','first','last')",
            name="ck_teacher_scheduling_rule_slots_selector",
        ),
        CheckConstraint(
            "(period_selector = 'period' AND period_index IS NOT NULL AND period_index > 0) OR "
            "(period_selector IN ('first','last') AND period_index IS NULL)",
            name="ck_teacher_scheduling_rule_slots_shape",
        ),
        UniqueConstraint(
            "rule_id", "day_key", "period_selector", "period_index",
            name="uq_teacher_scheduling_rule_slots_identity",
        ),
    )

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("teacher_scheduling_rules.id", ondelete="CASCADE"), nullable=False)
    day_key = Column(String(16), nullable=True)
    period_selector = Column(String(8), nullable=False, default="period")
    period_index = Column(Integer, nullable=True)


class TeacherSchedulingRuleTarget(Base):
    __tablename__ = "teacher_scheduling_rule_targets"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('grade','section')",
            name="ck_teacher_scheduling_rule_targets_type",
        ),
        CheckConstraint(
            "(target_type = 'grade' AND grade_level IS NOT NULL AND planning_section_id IS NULL) OR "
            "(target_type = 'section' AND planning_section_id IS NOT NULL AND grade_level IS NULL)",
            name="ck_teacher_scheduling_rule_targets_shape",
        ),
        ForeignKeyConstraint(
            ["planning_section_id", "branch_id", "academic_year_id"],
            ["planning_sections.id", "planning_sections.branch_id", "planning_sections.academic_year_id"],
            name="fk_teacher_scheduling_rule_targets_section_scope",
        ),
        UniqueConstraint(
            "rule_id", "target_type", "grade_level", "planning_section_id",
            name="uq_teacher_scheduling_rule_targets_identity",
        ),
    )

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("teacher_scheduling_rules.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"), nullable=False)
    target_type = Column(String(12), nullable=False)
    grade_level = Column(String(8), nullable=True)
    planning_section_id = Column(Integer, nullable=True)


class SubjectDistributionRule(Base):
    """Configurable HOW-distribution policy for one branch/year/grade/subject/section scope.

    Precedence is resolved in the application layer: section override, then
    grade+subject rule, then the branch/year default, then legacy behavior
    when no normalized row exists at all.
    """

    __tablename__ = "subject_distribution_rules"
    __table_args__ = (
        CheckConstraint(
            "scope_level IN ('branch_default','grade','section')",
            name="ck_subject_distribution_rules_scope_level",
        ),
        CheckConstraint(
            "scope_level <> 'branch_default' OR (grade_level IS NULL AND subject_code IS NULL AND section_id IS NULL)",
            name="ck_subject_distribution_rules_branch_default_shape",
        ),
        CheckConstraint(
            "scope_level = 'branch_default' OR (grade_level IS NOT NULL AND subject_code IS NOT NULL)",
            name="ck_subject_distribution_rules_grade_shape",
        ),
        CheckConstraint(
            "scope_level <> 'section' OR section_id IS NOT NULL",
            name="ck_subject_distribution_rules_section_shape",
        ),
        CheckConstraint(
            "require_daily_coverage IN ('auto','always','never')",
            name="ck_subject_distribution_rules_daily_coverage",
        ),
        CheckConstraint(
            "strictness IN ('hard','soft')",
            name="ck_subject_distribution_rules_strictness",
        ),
        CheckConstraint(
            "block_length >= 0 AND block_count >= 0 AND single_count >= 0",
            name="ck_subject_distribution_rules_nonnegative_counts",
        ),
        CheckConstraint(
            "min_teaching_days IS NULL OR min_teaching_days >= 0",
            name="ck_subject_distribution_rules_min_teaching_days",
        ),
        CheckConstraint(
            "max_periods_per_day IS NULL OR max_periods_per_day > 0",
            name="ck_subject_distribution_rules_max_periods_per_day",
        ),
        CheckConstraint(
            "min_day_gap IS NULL OR min_day_gap >= 0",
            name="ck_subject_distribution_rules_min_day_gap",
        ),
        Index(
            "uq_subject_distribution_rules_branch_default",
            "branch_id",
            "academic_year_id",
            unique=True,
            sqlite_where=text("scope_level = 'branch_default'"),
            postgresql_where=text("scope_level = 'branch_default'"),
        ),
        Index(
            "uq_subject_distribution_rules_grade",
            "branch_id",
            "academic_year_id",
            "grade_level",
            "subject_code",
            unique=True,
            sqlite_where=text("scope_level = 'grade'"),
            postgresql_where=text("scope_level = 'grade'"),
        ),
        Index(
            "uq_subject_distribution_rules_section",
            "branch_id",
            "academic_year_id",
            "grade_level",
            "subject_code",
            "section_id",
            unique=True,
            sqlite_where=text("scope_level = 'section'"),
            postgresql_where=text("scope_level = 'section'"),
        ),
        Index(
            "ix_subject_distribution_rules_scope",
            "branch_id",
            "academic_year_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"), nullable=False)
    scope_level = Column(String(16), nullable=False)
    grade_level = Column(String(8), nullable=True)
    subject_code = Column(String(20), nullable=True)
    section_id = Column(Integer, ForeignKey("planning_sections.id"), nullable=True)
    block_length = Column(Integer, nullable=False, default=2)
    block_count = Column(Integer, nullable=False, default=0)
    single_count = Column(Integer, nullable=False, default=0)
    min_teaching_days = Column(Integer, nullable=True)
    max_periods_per_day = Column(Integer, nullable=True)
    require_daily_coverage = Column(String(16), nullable=False, default="auto")
    spread_distinct_days = Column(Boolean, nullable=False, default=True)
    avoid_consecutive = Column(Boolean, nullable=False, default=True)
    min_day_gap = Column(Integer, nullable=True)
    strictness = Column(String(8), nullable=False, default="soft")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    updated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)


class TimetableInputSnapshot(Base):
    __tablename__ = "timetable_input_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "school_group_id",
            "branch_id",
            "academic_year_id",
            name="uq_timetable_input_snapshots_id_scope",
        ),
        CheckConstraint(
            "snapshot_schema_version > 0",
            name="ck_timetable_input_snapshots_schema_version",
        ),
        Index(
            "ix_timetable_input_snapshots_scope_created",
            "school_group_id",
            "branch_id",
            "academic_year_id",
            "created_at",
        ),
        Index(
            "ix_timetable_input_snapshots_full_fingerprint",
            "full_input_fingerprint",
        ),
    )

    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"), nullable=False)
    snapshot_schema_version = Column(Integer, nullable=False, default=1)
    canonical_snapshot_json = Column(Text, nullable=False)
    planning_fingerprint = Column(String(64), nullable=False)
    period_configuration_fingerprint = Column(String(64), nullable=False)
    constraint_fingerprint = Column(String(64), nullable=False)
    lock_fingerprint = Column(String(64), nullable=False)
    full_input_fingerprint = Column(String(64), nullable=False)
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    provenance = Column(String(40), nullable=False, default="manual")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TimetableFeasibilityVerification(Base):
    __tablename__ = "timetable_feasibility_verifications"
    __table_args__ = (
        UniqueConstraint(
            "school_group_id", "branch_id", "academic_year_id", "authority_fingerprint",
            name="uq_timetable_feasibility_scope_fingerprint",
        ),
        CheckConstraint(
            "status IN ('checking','verified','conflict','timed_out','internal_error')",
            name="ck_timetable_feasibility_status",
        ),
        Index("ix_timetable_feasibility_scope_status", "school_group_id", "branch_id", "academic_year_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(String(36), nullable=False, default=lambda: str(uuid.uuid4()), unique=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"), nullable=False)
    input_snapshot_id = Column(Integer, ForeignKey("timetable_input_snapshots.id"), nullable=False)
    authority_fingerprint = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="checking")
    feasible_placements_json = Column(Text, nullable=True)
    diagnostics_json = Column(Text, nullable=False, default="[]")
    solver_metadata_json = Column(Text, nullable=False, default="{}")
    requested_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TimetableVersion(Base):
    __tablename__ = "timetable_versions"
    __table_args__ = (
        UniqueConstraint(
            "school_group_id",
            "branch_id",
            "academic_year_id",
            "version_number",
            name="uq_timetable_versions_scope_number",
        ),
        UniqueConstraint(
            "id",
            "school_group_id",
            "branch_id",
            "academic_year_id",
            name="uq_timetable_versions_id_full_scope",
        ),
        UniqueConstraint(
            "id",
            "branch_id",
            "academic_year_id",
            name="uq_timetable_versions_id_branch_year",
        ),
        CheckConstraint(
            "lifecycle_status IN ('draft','publication_ready','superseded','archived')",
            name="ck_timetable_versions_lifecycle_status",
        ),
        CheckConstraint(
            "origin IN ('manual','imported','generated','regenerated')",
            name="ck_timetable_versions_origin",
        ),
        CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 100)",
            name="ck_timetable_versions_quality_score",
        ),
        CheckConstraint(
            "edit_revision >= 0",
            name="ck_timetable_versions_edit_revision",
        ),
        Index("uq_timetable_versions_public_id", "public_id", unique=True),
        Index(
            "ix_timetable_versions_scope_status",
            "school_group_id",
            "branch_id",
            "academic_year_id",
            "lifecycle_status",
        ),
        Index("ix_timetable_versions_source", "source_version_id"),
        Index("ix_timetable_versions_snapshot", "input_snapshot_id"),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    lifecycle_status = Column(String(32), nullable=False, default="draft")
    origin = Column(String(24), nullable=False, default="manual")
    source_version_id = Column(Integer, ForeignKey("timetable_versions.id"), nullable=True)
    input_snapshot_id = Column(
        Integer,
        ForeignKey("timetable_input_snapshots.id"),
        nullable=False,
    )
    # Kept as a durable future link without a circular database foreign key;
    # TimetableGenerationRun.result_version_id is the constrained reverse link.
    generation_run_id = Column(Integer, nullable=True, index=True)
    created_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    generated_at = Column(DateTime, nullable=True)
    has_manual_changes = Column(Boolean, nullable=False, default=False)
    manual_change_count = Column(Integer, nullable=False, default=0)
    quality_score = Column(Integer, nullable=True)
    quality_summary_json = Column(Text, nullable=True)
    generation_seed = Column(Integer, nullable=True)
    solver_name = Column(String(80), nullable=True)
    solver_version = Column(String(40), nullable=True)
    solver_configuration_json = Column(Text, nullable=True)
    authority_fingerprint = Column(String(64), nullable=False)
    is_stale = Column(Boolean, nullable=False, default=False)
    stale_reason_json = Column(Text, nullable=False, default="[]")
    approved_at = Column(DateTime, nullable=True)
    approved_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    published_at = Column(DateTime, nullable=True)
    published_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    superseded_at = Column(DateTime, nullable=True)
    superseded_by_version_id = Column(Integer, ForeignKey("timetable_versions.id"), nullable=True)
    archived_at = Column(DateTime, nullable=True)
    archived_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    edit_revision = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TimetableGenerationRun(Base):
    __tablename__ = "timetable_generation_runs"
    __table_args__ = (
        UniqueConstraint(
            "school_group_id",
            "branch_id",
            "academic_year_id",
            "idempotency_key",
            name="uq_timetable_generation_runs_scope_idempotency",
        ),
        CheckConstraint(
            "request_mode IN ('generate','regenerate')",
            name="ck_timetable_generation_runs_request_mode",
        ),
        CheckConstraint(
            "status IN ('queued','running','validating','succeeded','infeasible','timed_out','stale_input','cancel_requested','cancelled','internal_error','concurrent_run_rejected')",
            name="ck_timetable_generation_runs_status",
        ),
        CheckConstraint(
            "progress_phase IN ('queued','building','solving','checking','saving','complete','failed','cancelled')",
            name="ck_timetable_generation_runs_progress_phase",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_timetable_generation_runs_attempt_count",
        ),
        Index(
            "ix_timetable_generation_runs_scope_status",
            "school_group_id",
            "branch_id",
            "academic_year_id",
            "status",
        ),
        Index("ix_timetable_generation_runs_snapshot", "input_snapshot_id"),
        Index(
            "ix_timetable_generation_runs_worker_claim",
            "status",
            "lease_expires_at",
            "queued_at",
        ),
        Index(
            "uq_timetable_generation_runs_active_scope",
            "school_group_id",
            "branch_id",
            "academic_year_id",
            unique=True,
            sqlite_where=text(
                "status IN ('queued','running','validating','cancel_requested')"
            ),
            postgresql_where=text(
                "status IN ('queued','running','validating','cancel_requested')"
            ),
        ),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(String(36), nullable=False, default=lambda: str(uuid.uuid4()), unique=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"), nullable=False)
    requested_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    request_mode = Column(String(20), nullable=False)
    source_version_id = Column(Integer, ForeignKey("timetable_versions.id"), nullable=True)
    source_edit_revision = Column(Integer, nullable=True)
    input_snapshot_id = Column(
        Integer,
        ForeignKey("timetable_input_snapshots.id"),
        nullable=False,
    )
    status = Column(String(32), nullable=False, default="queued")
    progress_phase = Column(String(24), nullable=False, default="queued")
    attempt_count = Column(Integer, nullable=False, default=0)
    solver_name = Column(String(80), nullable=True)
    solver_version = Column(String(40), nullable=True)
    solver_configuration_json = Column(Text, nullable=True)
    generation_seed = Column(Integer, nullable=True)
    diversity_configuration_json = Column(Text, nullable=True)
    queued_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    validating_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    lease_owner = Column(String(120), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    failure_category = Column(String(80), nullable=True)
    safe_failure_details = Column(Text, nullable=True)
    cancel_requested_at = Column(DateTime, nullable=True)
    cancel_requested_by_user_id = Column(
        String(10),
        ForeignKey("users.user_id"),
        nullable=True,
    )
    result_version_id = Column(Integer, ForeignKey("timetable_versions.id"), nullable=True)
    idempotency_key = Column(String(120), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TimetableActiveVersion(Base):
    __tablename__ = "timetable_active_versions"
    __table_args__ = (
        UniqueConstraint(
            "school_group_id",
            "branch_id",
            "academic_year_id",
            name="uq_timetable_active_versions_scope",
        ),
        ForeignKeyConstraint(
            ["timetable_version_id", "school_group_id", "branch_id", "academic_year_id"],
            [
                "timetable_versions.id",
                "timetable_versions.school_group_id",
                "timetable_versions.branch_id",
                "timetable_versions.academic_year_id",
            ],
            name="fk_timetable_active_versions_exact_scope",
        ),
        CheckConstraint(
            "revision >= 0",
            name="ck_timetable_active_versions_revision",
        ),
        Index("ix_timetable_active_versions_version", "timetable_version_id"),
    )

    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"), nullable=False)
    timetable_version_id = Column(Integer, nullable=False)
    activated_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    activated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    revision = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TimetableEntry(Base):
    __tablename__ = "timetable_entries"
    __table_args__ = (
        UniqueConstraint(
            "timetable_version_id",
            "planning_section_id",
            "day_key",
            "period_index",
            name="uq_timetable_entries_section_slot",
        ),
        UniqueConstraint(
            "timetable_version_id",
            "teacher_id",
            "day_key",
            "period_index",
            name="uq_timetable_entries_teacher_slot",
        ),
        ForeignKeyConstraint(
            ["timetable_version_id", "branch_id", "academic_year_id"],
            [
                "timetable_versions.id",
                "timetable_versions.branch_id",
                "timetable_versions.academic_year_id",
            ],
            name="fk_timetable_entries_version_scope",
        ),
        Index(
            "ix_timetable_entries_scope_section",
            "branch_id",
            "academic_year_id",
            "planning_section_id",
        ),
        Index(
            "ix_timetable_entries_scope_teacher",
            "branch_id",
            "academic_year_id",
            "teacher_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    timetable_version_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    academic_year_id = Column(
        Integer,
        ForeignKey("academic_years.id"),
        nullable=False,
    )
    planning_section_id = Column(
        Integer,
        ForeignKey("planning_sections.id"),
        nullable=False,
    )
    subject_code = Column(String, nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    day_key = Column(String(16), nullable=False)
    period_index = Column(Integer, nullable=False)
    is_locked = Column(Boolean, nullable=False, default=False)
    locked_at = Column(DateTime, nullable=True)
    locked_by_user_id = Column(String(10), ForeignKey("users.user_id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class HiringPlanDraft(Base):
    __tablename__ = "hiring_plan_drafts"
    __table_args__ = (
        Index(
            "uq_hiring_plan_drafts_scope_user",
            "branch_id",
            "academic_year_id",
            "user_id",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    academic_year_id = Column(
        Integer,
        ForeignKey("academic_years.id"),
        nullable=False,
        index=True,
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    plan_json = Column(Text, nullable=False, default="{}")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
