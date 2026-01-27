"""
Custom jobs for populating test data in Open edX.

These commands help quickly set up test students, enrollments, grades, and assessment data
for testing instructor reports and other features.
"""

from __future__ import annotations

import typing as t

import click

from tutor import fmt


@click.command("populatetestdata", help="Populate test students, enrollments, grades, and assessments")
@click.option(
    "-n",
    "--students",
    default=10,
    show_default=True,
    type=int,
    help="Number of test students to create",
)
@click.option(
    "--prefix",
    default="teststudent",
    show_default=True,
    help="Username prefix for test students",
)
@click.option(
    "--password",
    default="edx",
    show_default=True,
    help="Password for all test student accounts",
)
@click.option(
    "--modes",
    default="audit,verified,honor",
    show_default=True,
    help="Comma-separated enrollment modes to distribute students across",
)
@click.option(
    "--clear",
    is_flag=True,
    help="Clear existing test data before populating",
)
@click.option(
    "--inactive",
    default=2,
    show_default=True,
    type=int,
    help="Number of inactive enrollments to create (for pending_activations report)",
)
@click.option(
    "--pending",
    default=3,
    show_default=True,
    type=int,
    help="Number of pending enrollments to create (for pending_enrollments report)",
)
@click.argument("course_id")
def populatetestdata(
    students: int,
    prefix: str,
    password: str,
    modes: str,
    clear: bool,
    inactive: int,
    pending: int,
    course_id: str,
) -> t.Iterable[tuple[str, str]]:
    """
    Populate test data for a course.

    This command creates test students, enrolls them in the specified course,
    and generates realistic grades and assessment data.

    Example:
        tutor dev do populatetestdata course-v1:edX+DemoX+Demo_Course --students 20
    """

    template = f"""
echo "🚀 Populating test data for course: {course_id}"
echo "   Creating {students} test students with prefix '{prefix}'"

cat > /tmp/populate_test_data.py << 'SCRIPT_EOF'
import os
import sys
import random
import string
import json
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.timezone import now
from opaque_keys.edx.keys import CourseKey

# Import models
from common.djangoapps.student.models import CourseEnrollment, CourseEnrollmentAllowed, AnonymousUserId, UserProfile
from lms.djangoapps.grades.models import PersistentSubsectionGrade, PersistentCourseGrade, VisibleBlocks
from lms.djangoapps.courseware.models import StudentModule
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
import hashlib

User = get_user_model()

# Configuration
COURSE_ID = "{course_id}"
NUM_STUDENTS = {students}
PREFIX = "{prefix}"
PASSWORD = "{password}"
MODES = "{modes}".split(",")
CLEAR_DATA = {"True" if clear else "False"}
NUM_INACTIVE = {inactive}
NUM_PENDING = {pending}

try:
    course_key = CourseKey.from_string(COURSE_ID)
except Exception as e:
    print(f"❌ Invalid course ID: {{e}}")
    sys.exit(1)

# Verify course exists
try:
    course_overview = CourseOverview.objects.get(id=course_key)
    print(f"   Course: {{course_overview.display_name}}")
except CourseOverview.DoesNotExist:
    print(f"❌ Course not found: {{COURSE_ID}}")
    sys.exit(1)

# Clear existing data if requested
if CLEAR_DATA:
    print("\\n🗑️  Clearing existing test data...")
    test_users = User.objects.filter(username__startswith=PREFIX)
    user_count = test_users.count()

    if user_count > 0:
        CourseEnrollment.objects.filter(user__in=test_users, course_id=course_key).delete()
        PersistentSubsectionGrade.objects.filter(user_id__in=test_users, course_id=course_key).delete()
        PersistentCourseGrade.objects.filter(user_id__in=test_users, course_id=course_key).delete()
        StudentModule.objects.filter(student__in=test_users, course_id=course_key).delete()
        print(f"   ✓ Cleared data for {{user_count}} test users")
    else:
        print("   ℹ No existing test data found")

with transaction.atomic():
    # Create students
    print(f"\\n📝 Creating {{NUM_STUDENTS}} students...")
    students = []
    for i in range(1, NUM_STUDENTS + 1):
        username = f'{{PREFIX}}{{i}}'
        user, created = User.objects.get_or_create(
            username=username,
            defaults={{
                'email': f'{{username}}@example.com',
                'first_name': 'Test',
                'last_name': f'Student {{i}}',
                'is_active': True,
            }}
        )
        if created:
            user.set_password(PASSWORD)
            user.save()
            print(f"   ✓ Created user: {{username}}")
        else:
            print(f"   ℹ Using existing user: {{username}}")

        # Create UserProfile - keep it minimal like real users (mostly empty)
        # This matches the pattern of real users in the system
        # Always create/get profile, not just for new users
        UserProfile.objects.get_or_create(
            user=user,
            defaults={{
                'name': '',  # Empty like real users
                'language': '',
                'location': '',
                'year_of_birth': None,
                'gender': None,
                'level_of_education': None,
                'mailing_address': '',
                'goals': '',
                'city': '',
                'country': '',
            }}
        )
        students.append(user)

    # Enroll students
    print(f"\\n📚 Enrolling students...")
    enrollments = []
    for i, student in enumerate(students):
        mode = MODES[i % len(MODES)]
        enrollment, created = CourseEnrollment.objects.get_or_create(
            user=student,
            course_id=course_key,
            defaults={{'mode': mode, 'is_active': True}}
        )
        if not created:
            enrollment.mode = mode
            enrollment.is_active = True
            enrollment.save()
        enrollments.append(enrollment)
    print(f"   ✓ Enrolled {{len(enrollments)}} students")

    # Create grades
    print(f"\\n📊 Creating grades...")
    num_subsections = random.randint(5, 10)
    subsections = [
        course_key.make_usage_key('sequential', f'subsection_{{i+1}}')
        for i in range(num_subsections)
    ]

    grade_summary = {{'A': 0, 'B': 0, 'C': 0, 'D': 0, 'F': 0}}

    # Create a visible blocks object for the grades
    blocks_json = '[]'  # Empty block list
    blocks_hash = hashlib.sha1(blocks_json.encode('utf-8')).hexdigest()
    visible_blocks, _ = VisibleBlocks.objects.get_or_create(
        hashed=blocks_hash,
        defaults={{
            'blocks_json': blocks_json,
            'course_id': course_key,
        }}
    )

    for student in students:
        total_earned = 0
        total_possible = 0

        for usage_key in subsections:
            earned = random.uniform(0.0, 1.0)
            possible = 1.0
            total_earned += earned
            total_possible += possible

            PersistentSubsectionGrade.objects.update_or_create(
                user_id=student.id,
                course_id=course_key,
                usage_key=usage_key,
                defaults={{
                    'earned_all': earned,
                    'possible_all': possible,
                    'earned_graded': earned,
                    'possible_graded': possible,
                    'first_attempted': now() - timedelta(days=random.randint(1, 30)),
                    'visible_blocks': visible_blocks,
                }}
            )

        # Create course grade
        if total_possible > 0:
            percent_grade = total_earned / total_possible
            if percent_grade >= 0.9:
                letter_grade = 'A'
            elif percent_grade >= 0.8:
                letter_grade = 'B'
            elif percent_grade >= 0.7:
                letter_grade = 'C'
            elif percent_grade >= 0.6:
                letter_grade = 'D'
            else:
                letter_grade = 'F'

            grade_summary[letter_grade] += 1

            PersistentCourseGrade.objects.update_or_create(
                user_id=student.id,
                course_id=course_key,
                defaults={{
                    'percent_grade': percent_grade,
                    'letter_grade': letter_grade,
                    'passed_timestamp': now() if percent_grade >= 0.6 else None,
                }}
            )

    print(f"   ✓ Created grades for {{len(students)}} students")
    print(f"   Grade distribution: A={{grade_summary['A']}}, B={{grade_summary['B']}}, C={{grade_summary['C']}}, D={{grade_summary['D']}}, F={{grade_summary['F']}}")

    # Create student modules (problem attempts)
    print(f"\\n✍️  Creating assessment data...")
    num_problems = random.randint(5, 15)
    problems = [
        course_key.make_usage_key('problem', f'problem_{{i+1}}')
        for i in range(num_problems)
    ]

    total_attempts = 0
    for student in students:
        num_attempted = random.randint(3, min(len(problems), 10))
        attempted_problems = random.sample(problems, num_attempted)

        for problem_key in attempted_problems:
            max_grade = random.randint(1, 10)
            grade = random.uniform(0, max_grade)
            attempts = random.randint(1, 3)

            state = {{
                'seed': random.randint(1, 1000),
                'student_answers': {{}},
                'correct_map': {{}},
                'input_state': {{}},
                'attempts': attempts,
            }}

            StudentModule.objects.update_or_create(
                student=student,
                course_id=course_key,
                module_state_key=problem_key,
                defaults={{
                    'grade': grade,
                    'max_grade': max_grade,
                    'state': json.dumps(state),
                    'module_type': 'problem',
                    'done': 'na',
                }}
            )
            total_attempts += 1

    print(f"   ✓ Created {{total_attempts}} problem attempts across {{len(students)}} students")

    # Create inactive users with active enrollments (for pending_activations report)
    if NUM_INACTIVE > 0:
        print(f"\\n💤 Creating {{NUM_INACTIVE}} pending activations (inactive users with active enrollments)...")
        for i in range(NUM_INACTIVE):
            username = f'{{PREFIX}}_inactive{{i+1}}'
            user, created = User.objects.get_or_create(
                username=username,
                defaults={{
                    'email': f'{{username}}@example.com',
                    'first_name': 'Inactive',
                    'last_name': f'Student {{i+1}}',
                    'is_active': False,  # Inactive user
                }}
            )
            if created:
                user.set_password(PASSWORD)
                user.save()

            # Create UserProfile for inactive user
            UserProfile.objects.get_or_create(
                user=user,
                defaults={{
                    'name': '',
                    'language': '',
                    'location': '',
                    'year_of_birth': None,
                    'gender': None,
                    'level_of_education': None,
                    'mailing_address': '',
                    'goals': '',
                    'city': '',
                    'country': '',
                }}
            )

            # Create ACTIVE enrollment for inactive user (pending activation)
            CourseEnrollment.objects.get_or_create(
                user=user,
                course_id=course_key,
                defaults={{
                    'mode': 'audit',
                    'is_active': True,  # Active enrollment
                }}
            )
        print(f"   ✓ Created {{NUM_INACTIVE}} pending activations")

    # Create pending enrollments (for pending_enrollments report)
    if NUM_PENDING > 0:
        print(f"\\n⏳ Creating {{NUM_PENDING}} pending enrollments...")
        for i in range(NUM_PENDING):
            email = f'{{PREFIX}}_pending{{i+1}}@example.com'
            CourseEnrollmentAllowed.objects.get_or_create(
                email=email,
                course_id=course_key,
                defaults={{'auto_enroll': True}}
            )
        print(f"   ✓ Created {{NUM_PENDING}} pending enrollments")

    # Create anonymous user IDs (for anonymized_student_ids report)
    print(f"\\n🔒 Creating anonymous user IDs...")
    anon_count = 0
    for student in students:
        # Create anonymous ID for each enrolled student
        anonymous_id = f'{{hashlib.md5(f"{{student.id}}-{{COURSE_ID}}".encode()).hexdigest()}}'
        AnonymousUserId.objects.get_or_create(
            user=student,
            course_id=course_key,
            defaults={{'anonymous_user_id': anonymous_id}}
        )
        anon_count += 1
    print(f"   ✓ Created {{anon_count}} anonymous user IDs")

print(f"\\n✅ Test data population complete!")
print(f"\\n📋 Summary:")
print(f"   Active students: {{NUM_STUDENTS}} ({{PREFIX}}1 through {{PREFIX}}{{NUM_STUDENTS}})")
print(f"   Inactive enrollments: {{NUM_INACTIVE}}")
print(f"   Pending enrollments: {{NUM_PENDING}}")
print(f"   Anonymous IDs: {{anon_count}}")
print(f"   Password: {{PASSWORD}}")
print(f"   Email format: {{PREFIX}}N@example.com")
print(f"   Enrollment modes: {{', '.join(MODES)}}")
print(f"   Subsections: {{num_subsections}}")
print(f"   Problems: {{num_problems}}")
print()
print('✨ Ready to test ALL instructor reports!')
SCRIPT_EOF

./manage.py lms shell < /tmp/populate_test_data.py
"""

    yield ("lms", template)


@click.command("cleartestdata", help="Clear test data for specific course")
@click.option(
    "--prefix",
    default="teststudent",
    show_default=True,
    help="Username prefix for test students to clear",
)
@click.argument("course_id")
def cleartestdata(prefix: str, course_id: str) -> t.Iterable[tuple[str, str]]:
    """
    Clear test data for a specific course.

    This removes enrollments, grades, and assessment data for test users.

    Example:
        tutor dev do cleartestdata course-v1:edX+DemoX+Demo_Course
    """

    template = f"""
echo "🗑️  Clearing test data for course: {course_id}"

cat > /tmp/clear_test_data.py << 'SCRIPT_EOF'
import sys
from django.contrib.auth import get_user_model
from opaque_keys.edx.keys import CourseKey

from common.djangoapps.student.models import CourseEnrollment, CourseEnrollmentAllowed, AnonymousUserId, UserProfile
from lms.djangoapps.grades.models import PersistentSubsectionGrade, PersistentCourseGrade
from lms.djangoapps.courseware.models import StudentModule

User = get_user_model()

COURSE_ID = '{course_id}'
PREFIX = '{prefix}'

try:
    course_key = CourseKey.from_string(COURSE_ID)
except Exception as e:
    print(f'❌ Invalid course ID: {{e}}')
    sys.exit(1)

# Find all test users (including inactive ones)
test_users = User.objects.filter(username__startswith=PREFIX)
user_count = test_users.count()

# Also find pending enrollment emails
pending_emails = list(CourseEnrollmentAllowed.objects.filter(
    course_id=course_key,
    email__startswith=PREFIX
).values_list('email', flat=True))

if user_count == 0 and len(pending_emails) == 0:
    print(f'ℹ No test data found with prefix "{{PREFIX}}"')
    sys.exit(0)

print(f'Found {{user_count}} test users and {{len(pending_emails)}} pending enrollments')

# Delete course-related data
enrollments_deleted = CourseEnrollment.objects.filter(user__in=test_users, course_id=course_key).delete()[0]
subsection_grades_deleted = PersistentSubsectionGrade.objects.filter(user_id__in=test_users, course_id=course_key).delete()[0]
course_grades_deleted = PersistentCourseGrade.objects.filter(user_id__in=test_users, course_id=course_key).delete()[0]
modules_deleted = StudentModule.objects.filter(student__in=test_users, course_id=course_key).delete()[0]
anonymous_ids_deleted = AnonymousUserId.objects.filter(user__in=test_users, course_id=course_key).delete()[0]
pending_deleted = CourseEnrollmentAllowed.objects.filter(course_id=course_key, email__startswith=PREFIX).delete()[0]

print(f'✓ Deleted {{enrollments_deleted}} enrollments')
print(f'✓ Deleted {{subsection_grades_deleted}} subsection grades')
print(f'✓ Deleted {{course_grades_deleted}} course grades')
print(f'✓ Deleted {{modules_deleted}} student modules')
print(f'✓ Deleted {{anonymous_ids_deleted}} anonymous user IDs')
print(f'✓ Deleted {{pending_deleted}} pending enrollments')
print()
print(f'✅ Test data cleared for {{user_count}} users and {{len(pending_emails)}} pending enrollments')
print()
print('Note: Test user accounts and profiles still exist but are no longer enrolled in this course.')
print(f'To completely remove user accounts and profiles, run: ./manage.py lms shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.filter(username__startswith=\\'{{PREFIX}}\\').delete()"')
SCRIPT_EOF

./manage.py lms shell < /tmp/clear_test_data.py
"""

    yield ("lms", template)
