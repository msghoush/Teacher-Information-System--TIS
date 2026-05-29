from collections import defaultdict
from io import BytesIO
import base64
from datetime import date, datetime, timedelta, timezone
import html
import json
import logging
import os
import traceback
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

import auth
import models
from auth import get_current_user
from database import engine
from dependencies import get_db
from ui_shell import build_shell_context, get_school_logo_slots


router = APIRouter(prefix="/observations", tags=["Observations"])
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger("tis.observations")

FORMAL_OBSERVATION_TARGET = 6
RATING_VALUES = {"0", "1", "2", "3", "4", "5"}
DEFAULT_DISPLAY_TIMEZONE = "Asia/Riyadh"

OBSERVATION_CRITERIA = [{'domain_key': 'A',
  'domain_title': 'Planning and Preparation',
  'indicator_number': 1,
  'title': 'Develops a focused and logically staged lesson with clearly stated and appropriate lesson objectives',
  'guidelines': '- Clarity of Objectives: Objectives are clearly stated, measurable, and aligned with what students are expected to learn. '
                '- Logical Sequencing: Lesson follows a structured order (prior knowledge → new input → practice → application). - '
                'Relevance: Objectives connect to curriculum standards while also being meaningful for learners. - Differentiation: Plans '
                'include strategies for diverse abilities, learning styles, and needs. - Feasibility and Resources: Objectives are '
                'realistic within the time and achievable with prepared resources.',
  'evidence_examples': '- Teacher writes objectives on the board and explains them in student-friendly language; students can restate them '
                       'in their own words. - Activities flow smoothly from review to independent work; students are not confused. - '
                       'Teacher relates fractions to pizza sharing; students make real-life connections. - Struggling learners use '
                       'fraction tiles; advanced learners solve mixed-number problems. - Worksheets, visuals, and digital tools are '
                       'prepared in advance to support objectives.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'No objectives are stated; lesson lacks structure or clarity.',
                         '1': 'Objectives are vague or overly broad; sequencing is disorganized; activities appear disconnected.',
                         '2': 'Objectives are partially clear but not fully measurable; lesson shows some sequencing but limited '
                              'connection to prior knowledge or student needs.',
                         '3': 'Objectives are clear and measurable; lesson follows a mostly logical sequence (review → new input → '
                              'practice → application); some differentiation is attempted.',
                         '4': 'Objectives are very clear, student-friendly, measurable, and aligned to curriculum; sequencing flows '
                              'logically with smooth transitions; activities are relevant and differentiated for diverse learners.',
                         '5': 'Objectives are crystal clear, innovative, and inspiring; sequencing is seamless; activities show '
                              'creativity, strong differentiation, and real-life connections; students can restate objectives in their own '
                              'words. Supported by proof: lesson plan, board notes, or student responses.'}},
 {'domain_key': 'A',
  'domain_title': 'Planning and Preparation',
  'indicator_number': 2,
  'title': 'Lesson is aligned with the weekly plan',
  'guidelines': '- Consistency with Curriculum: Lesson aligns with broader curriculum and weekly plan. - Connection to Previous and Future '
                'Lessons: Links are made to past lessons and previews of upcoming content. - Pacing: Lesson timing aligns with the weekly '
                'plan for balanced coverage. - Adaptability: Teacher adjusts while keeping weekly goals intact. - Assessment Integration: '
                'Lesson includes informal or formal checks for understanding.',
  'evidence_examples': '- Teacher reviews comparing fractions (past) and previews comparing unlike denominators (future). - Pacing is '
                       'structured: 10 min review → 20 min new learning → 10 min practice → 5 min reflection. - Teacher adapts if students '
                       'struggle but still meets weekly goals. - Students complete exit slips to demonstrate understanding.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Lesson shows no alignment to the weekly plan or curriculum scope; pacing is off track.',
                         '1': 'Limited evidence of alignment; lesson loosely connects to curriculum but lacks continuity or pacing.',
                         '2': 'Some alignment with the weekly plan; lesson partially connects to previous or future lessons but '
                              'inconsistently; pacing may be uneven.',
                         '3': 'Lesson is clearly aligned to the weekly plan and curriculum; connects to prior knowledge and builds toward '
                              'future content; pacing is mostly appropriate.',
                         '4': 'Lesson is fully aligned with curriculum and weekly scope; pacing is smooth and balanced; clear links to '
                              'prior/future learning are established; assessment is integrated.',
                         '5': 'Lesson demonstrates excellent alignment and continuity across unit/weekly plan; pacing is dynamic yet '
                              'efficient; links to past and future learning are explicit; assessments and adaptation strategies enrich '
                              'continuity. Supported by proof: weekly plan reference, student work, assessments.'}},
 {'domain_key': 'B',
  'domain_title': 'Culture/Climate Dimension',
  'indicator_number': 1,
  'title': 'Fosters an environment that embraces all learners',
  'guidelines': '- Inclusivity and Belonging: Every learner feels accepted and valued regardless of background, ability, or style. - '
                'Respect for Diversity: Materials, discussions, and examples reflect cultural sensitivity. - Support for All Learners: '
                'Instruction makes every student feel capable of success.',
  'evidence_examples': '- Teacher uses students’ names and acknowledges contributions. - Displays include diverse cultures, genders, and '
                       'abilities. - Group work is structured so all learners participate. - Teacher adapts examples to reflect students’ '
                       'lives.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Teacher shows no attempt to build an inclusive classroom; some students feel excluded or ignored.',
                         '1': 'Teacher inconsistently acknowledges students; inclusivity is minimal; classroom may reflect bias or '
                              'favoritism.',
                         '2': 'Teacher attempts inclusivity but with limited strategies; some students feel valued, others less so.',
                         '3': 'Teacher creates a generally inclusive environment; students are acknowledged and feel welcome; classroom '
                              'climate is mostly positive.',
                         '4': 'Teacher deliberately integrates inclusive practices; students consistently feel respected and represented; '
                              'classroom materials reflect diversity.',
                         '5': 'Teacher creates a classroom culture where every learner feels celebrated; inclusivity is deeply embedded '
                              '(language, materials, group work, discussions); learners actively model respect for diversity. Supported by '
                              'proof: classroom displays, group activities, student feedback.'}},
 {'domain_key': 'B',
  'domain_title': 'Culture/Climate Dimension',
  'indicator_number': 2,
  'title': 'Treats each learner equitably',
  'guidelines': '- Fairness in Interaction: All students have equal opportunities to participate. - Consistency: Expectations, rewards, '
                'and discipline are applied fairly. - Bias-Free Approach: No favoritism, stereotypes, or unequal treatment.',
  'evidence_examples': '- Teacher rotates who answers questions. - Praise is distributed fairly based on effort and achievement. - Rules '
                       'are enforced equally for all students.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Teacher applies rules, praise, or discipline unfairly; favoritism or bias is evident.',
                         '1': 'Attempts fairness but is inconsistent; some learners receive more attention or opportunities than others.',
                         '2': 'Some improvement in fairness; teacher distributes praise, questions, and support unevenly but with partial '
                              'awareness.',
                         '3': 'Teacher treats students fairly and applies rules consistently; most learners feel equally valued.',
                         '4': 'Teacher consistently demonstrates fairness and impartiality; all learners are given equal opportunities to '
                              'participate, contribute, and access resources.',
                         '5': 'Teacher actively models equity and advocates for fairness; classroom culture ensures all learners feel '
                              'equally important; students demonstrate fairness in peer interactions. Supported by proof: observer notes, '
                              'student participation records, discipline logs.'}},
 {'domain_key': 'B',
  'domain_title': 'Culture/Climate Dimension',
  'indicator_number': 3,
  'title': 'Encourages learners to share their opinions without fear of negative comments from their peers',
  'guidelines': '- Safe Learning Environment: Students feel safe to express themselves. - Respectful Dialogue: Norms for respectful '
                'discussions are established. - Risk-Taking Encouraged: Learners share even if answers are not perfect.',
  'evidence_examples': '- Teacher says: “In this classroom, all ideas are welcome.” - Mistakes are treated as learning opportunities. - '
                       'Teacher addresses ridicule immediately. - Debates include acknowledgment of all viewpoints.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Teacher does not encourage learners to share; classroom feels unsafe for student voice.',
                         '1': 'Limited encouragement of student voice; some students hesitate to share due to peer reactions.',
                         '2': 'Teacher occasionally fosters open discussion but struggles to prevent ridicule or negativity.',
                         '3': 'Teacher encourages learners to share opinions; respectful dialogue is promoted; negative comments are '
                              'addressed when they arise.',
                         '4': 'Teacher actively fosters a safe environment where learners feel comfortable expressing opinions; respectful '
                              'dialogue is consistently enforced.',
                         '5': 'Teacher creates a culture of trust and openness; all voices are valued; learners support and encourage each '
                              'other’s contributions; mistakes are celebrated as learning opportunities. Supported by proof: student '
                              'discussions, observation notes, peer interactions.'}},
 {'domain_key': 'B',
  'domain_title': 'Culture/Climate Dimension',
  'indicator_number': 4,
  'title': 'Creates enthusiasm for the learning at hand',
  'guidelines': '- Teacher Energy and Attitude: Models excitement and passion. - Engagement Strategies: Lessons spark curiosity. - '
                'Celebration of Success: Recognizes student effort and progress.',
  'evidence_examples': '- Teacher begins with a thought-provoking question or real-world scenario. - Voice, body language, and expressions '
                       'show enthusiasm. - Teacher praises effort and posts student work on the wall.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Teacher shows little or no enthusiasm; students appear disengaged or uninterested.',
                         '1': 'Teacher occasionally shows energy but inconsistently; limited impact on student motivation.',
                         '2': 'Teacher demonstrates some enthusiasm; students are somewhat engaged but inconsistently.',
                         '3': 'Teacher models enthusiasm through tone, energy, and relevant examples; students show interest and '
                              'participate.',
                         '4': 'Teacher consistently uses engaging strategies, celebrates student success, and inspires active '
                              'participation; learners demonstrate curiosity.',
                         '5': 'Teacher’s enthusiasm is contagious; learners are highly motivated, excited, and take ownership of their '
                              'learning; classroom energy is consistently positive and inspiring. Supported by proof: student engagement '
                              'levels, observer notes, lesson recordings.'}},
 {'domain_key': 'C',
  'domain_title': 'Learning Dimension',
  'indicator_number': 1,
  'title': 'Communicates clear explanations about the activities or tasks',
  'guidelines': '- Provides step-by-step instructions using clear, simple, and direct language. - Connects activities to the overall '
                'lesson objectives so students understand why they are doing them. - Anticipates areas of confusion and proactively '
                'clarifies. - Checks for understanding before moving on.',
  'evidence_examples': '- Teacher says: “First, work with your partner to solve question one. Then, we’ll discuss as a group.” - '
                       'Instructions are repeated or rephrased for clarity. - Teacher asks: “Who can explain what we’re supposed to do?” '
                       'to confirm understanding. - Visual aids (written steps on the board) support verbal instructions.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Teacher does not provide instructions; students are confused.',
                         '1': 'Instructions are vague, incomplete, or unclear; little connection to objectives.',
                         '2': 'Instructions are sometimes clear but inconsistent; students require repeated clarification.',
                         '3': 'Instructions are generally clear and step-by-step; most students understand the tasks.',
                         '4': 'Instructions are consistently clear, concise, and connected to objectives; misunderstandings are rare.',
                         '5': 'Instructions are crystal clear, scaffolded, and supported by visuals/examples; students can restate '
                              'instructions independently. Supported by proof: lesson observation, student feedback.'}},
 {'domain_key': 'C',
  'domain_title': 'Learning Dimension',
  'indicator_number': 2,
  'title': 'Implements lessons and/or activities that stimulate learners to use higher order thinking skills',
  'guidelines': '- Designs tasks that require analysis, evaluation, and creation, not just recall. - Uses open-ended and thought-provoking '
                'questions. - Encourages learners to justify their reasoning. - Provides opportunities for discussion, debate, and '
                'problem-solving.',
  'evidence_examples': '- Students compare two different problem-solving methods and explain which is more efficient. - Teacher asks: “Why '
                       'do you think this character acted that way? What would you have done differently?” - In science, students design '
                       'their own experiment instead of only following steps.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Activities require only rote recall or passive learning; no evidence of higher-order thinking.',
                         '1': 'Limited use of open-ended questions or tasks; higher-order thinking rarely encouraged.',
                         '2': 'Some activities encourage analysis/evaluation but inconsistently; limited student engagement.',
                         '3': 'Activities regularly include opportunities for analysis, application, or problem-solving.',
                         '4': 'Activities consistently require higher-order thinking (analysis, evaluation, creation); students are '
                              'actively engaged in deeper discussions.',
                         '5': 'Activities foster creativity, innovation, and independent inquiry; learners pose their own critical '
                              'questions and engage in sophisticated reasoning. Supported by proof: student work samples, class '
                              'discussions.'}},
 {'domain_key': 'C',
  'domain_title': 'Learning Dimension',
  'indicator_number': 3,
  'title': 'Delivers lessons that are relatable to the learners or aligned to their interests',
  'guidelines': '- Connects content to learners’ personal experiences and cultural backgrounds. - Uses real-life examples relevant to age, '
                'interests, and environment. - Highlights applications of content to everyday life. - Adapts instruction to reflect '
                'learners’ passions and hobbies.',
  'evidence_examples': '- Math lesson includes calculating sports statistics for students who enjoy football. - History lesson connects '
                       'past events to current issues in the community. - Teacher asks students to share examples from their lives that '
                       'connect to the lesson.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'No attempt to connect lessons to student interests, experiences, or context.',
                         '1': 'Occasional attempt to relate content but mostly irrelevant or superficial.',
                         '2': 'Some lessons connect to learners’ lives or interests, but inconsistently.',
                         '3': 'Lessons are often connected to learners’ experiences; students show interest and engagement.',
                         '4': 'Lessons are consistently relatable, using real-world and culturally relevant examples that connect with '
                              'learners’ passions.',
                         '5': 'Lessons are deeply meaningful; learners see personal relevance and make their own connections; enthusiasm '
                              'and motivation are highly evident. Supported by proof: lesson plans, student reflections, engagement '
                              'observations.'}},
 {'domain_key': 'C',
  'domain_title': 'Learning Dimension',
  'indicator_number': 4,
  'title': 'Monitors learners’ understanding of the content and/or the acquisition of skills',
  'guidelines': '- Uses questioning and observation to check comprehension during lessons. - Employs formative assessments (exit slips, '
                'quizzes, mini whiteboards). - Encourages self-assessment and peer feedback. - Provides corrective support when '
                'misconceptions arise.',
  'evidence_examples': '- Teacher circulates the classroom, checking students’ work and asking questions. - At the end of the lesson, '
                       'students complete a 2-minute exit slip summarizing the main idea. - Peer-review activities allow learners to give '
                       'each other feedback. - Teacher re-explains a concept when noticing repeated errors.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'No checks for understanding; teacher is unaware of students’ progress.',
                         '1': 'Minimal attempts to check understanding; feedback is absent or very limited.',
                         '2': 'Some monitoring occurs, but inconsistently; misconceptions are sometimes overlooked.',
                         '3': 'Teacher regularly checks for understanding through questioning, observation, or quick assessments; feedback '
                              'is provided.',
                         '4': 'Monitoring is systematic; teacher uses varied strategies (exit slips, peer checks, questioning) to adjust '
                              'instruction.',
                         '5': 'Monitoring is continuous, adaptive, and student-centered; learners also self-assess and peer-assess; '
                              'feedback is timely and actionable. Supported by proof: assessment tools, observation notes, student '
                              'feedback.'}},
 {'domain_key': 'C',
  'domain_title': 'Learning Dimension',
  'indicator_number': 5,
  'title': 'Adapts instruction and/or activities that meet individual learner’s needs',
  'guidelines': '- Adjusts tasks based on student ability and progress. - Provides multiple entry points to the same concept (visual, '
                'auditory, kinesthetic). - Groups students flexibly (pairs, small groups, whole class). - Offers choices in assignments '
                'and tasks.',
  'evidence_examples': '- Struggling readers get simplified texts with visuals, while advanced readers tackle primary sources. - Teacher '
                       'allows choice between writing a report, making a poster, or giving a short presentation. - During group work, '
                       'teacher rearranges groups to support peer learning.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'No evidence of adaptation; instruction is one-size-fits-all.',
                         '1': 'Minimal differentiation; some learners are left behind or unchallenged.',
                         '2': 'Some adaptation occurs, but limited in scope; not all learners are supported.',
                         '3': 'Instruction is adapted for groups of learners; differentiated strategies are used to support and challenge '
                              'most students.',
                         '4': 'Instruction is consistently adapted to meet varied needs; teacher uses flexible grouping, scaffolding, and '
                              'choice.',
                         '5': 'Instruction is highly personalized; students take ownership of differentiated pathways; learning is '
                              'inclusive, equitable, and challenging for all. Supported by proof: lesson plan differentiation notes, '
                              'observation records, student work.'}},
 {'domain_key': 'C',
  'domain_title': 'Learning Dimension',
  'indicator_number': 6,
  'title': 'Provides learners with purposeful feedback about their progress and/or needs',
  'guidelines': '- Gives feedback that is timely, specific, and constructive. - Balances praise with areas for improvement. - Provides '
                'feedback in written, oral, or digital form. - Encourages learners to act on feedback and reflect.',
  'evidence_examples': '- Teacher writes: “Great use of vocabulary—next time, add more evidence from the text.” - During class, teacher '
                       'says: “I like how you explained your reasoning. Can you expand on it?” - Students keep reflection journals to '
                       'track feedback and improvement. - Teacher conferences with students individually to discuss progress.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'No feedback is given; learners have no awareness of progress.',
                         '1': 'Feedback is rare, vague, or generic (e.g., “Good job”).',
                         '2': 'Some feedback is provided but not always specific or timely; limited impact on learning.',
                         '3': 'Feedback is clear, specific, and mostly timely; learners use it to improve.',
                         '4': 'Feedback is consistent, purposeful, and growth-oriented; students act on it effectively.',
                         '5': 'Feedback is highly impactful—timely, constructive, and learner-centered; students reflect, track progress, '
                              'and set goals based on feedback. Supported by proof: written feedback samples, student reflection '
                              'journals.'}},
 {'domain_key': 'D',
  'domain_title': 'Essentials Dimension',
  'indicator_number': 1,
  'title': 'Delivers and/or facilitates the lesson with knowledge and confidence',
  'guidelines': '- Demonstrates strong command of subject matter and communicates concepts clearly. - Uses accurate examples and '
                'explanations. - Speaks with confidence, clarity, and appropriate tone. - Anticipates students’ questions and responds '
                'effectively. - Connects new learning to broader concepts for deeper understanding.',
  'evidence_examples': '- Teacher explains a math process step-by-step without hesitation and connects it to real-world use (e.g., '
                       'budgeting). - In science, the teacher anticipates a common misconception and clarifies before it arises. - Teacher '
                       'uses confident body language, clear voice projection, and maintains student attention.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Teacher shows little or no subject knowledge; explanations are unclear or inaccurate.',
                         '1': 'Teacher demonstrates limited subject knowledge; frequent inaccuracies; lacks confidence in delivery.',
                         '2': 'Teacher demonstrates partial knowledge; explanations are sometimes correct but lack depth.',
                         '3': 'Teacher demonstrates good subject knowledge and confidence; explanations are clear and mostly accurate.',
                         '4': 'Teacher demonstrates strong command of subject matter; explanations are confident, accurate, and connected '
                              'to broader concepts.',
                         '5': 'Teacher demonstrates mastery and enthusiasm; explanations are insightful, accurate, and inspiring; teacher '
                              'anticipates misconceptions and extends learning creatively. Supported by proof: lesson observation, student '
                              'responses.'}},
 {'domain_key': 'D',
  'domain_title': 'Essentials Dimension',
  'indicator_number': 2,
  'title': 'Communicates and upholds high expectations for learners’ behaviors to maximize their learning and well-being',
  'guidelines': '- Clearly states behavioral expectations at the start of the year/lesson. - Uses consistent routines and fair enforcement '
                'of rules. - Encourages responsibility for self-discipline and respect. - Promotes positive behavior through '
                'reinforcement. - Links behavior expectations to academic success and well-being.',
  'evidence_examples': '- Teacher says: “In this class, we listen while others speak.” and follows through if interrupted. - Students know '
                       'routines for entering class, transitioning, and asking questions. - Teacher praises positive behaviors (e.g., '
                       'teamwork, focus) and redirects misbehavior calmly and consistently.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'No behavior expectations are set; classroom is disorganized; learning time is lost.',
                         '1': 'Expectations are vague or inconsistently enforced; students are sometimes unclear about boundaries.',
                         '2': 'Some behavior expectations are communicated but inconsistently upheld; classroom management is uneven.',
                         '3': 'Teacher communicates clear expectations; applies rules fairly; classroom is orderly and conducive to '
                              'learning.',
                         '4': 'Expectations are consistently upheld; teacher reinforces positive behaviors; students feel safe and '
                              'respected.',
                         '5': 'Expectations are deeply embedded in class culture; students take responsibility for their own and peers’ '
                              'behavior; high levels of respect, responsibility, and self-regulation are evident. Supported by proof: '
                              'observation notes, student behavior records.'}},
 {'domain_key': 'D',
  'domain_title': 'Essentials Dimension',
  'indicator_number': 3,
  'title': 'Facilitates use of resources that support learners’ needs',
  'guidelines': '- Selects resources that align with lesson objectives and student needs. - Provides access to a variety of tools (print, '
                'digital, manipulatives). - Ensures resources are safe, age-appropriate, and inclusive. - Uses technology effectively to '
                'enhance learning (not distract). - Models correct and safe use of materials.',
  'evidence_examples': '- Students use tablets for interactive practice, but tasks remain purposeful and guided. - In science, students '
                       'use lab equipment with clear safety instructions. - The teacher prepares visuals, charts, and manipulatives for '
                       'learners who need extra support.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Teacher provides no or irrelevant resources; students lack tools for learning.',
                         '1': 'Limited resources are used; resources are sometimes misaligned or inappropriate.',
                         '2': 'Some resources are used but not consistently effective or engaging.',
                         '3': 'Teacher selects appropriate resources aligned to objectives; students benefit from them.',
                         '4': 'Resources are consistently purposeful, age-appropriate, inclusive, and enhance learning; technology is used '
                              'meaningfully.',
                         '5': 'Resources are highly engaging, diverse, and personalized to learners’ needs; students skillfully use '
                              'resources independently; technology integration is seamless and innovative. Supported by proof: resource '
                              'lists, classroom observation, student work.'}},
 {'domain_key': 'D',
  'domain_title': 'Essentials Dimension',
  'indicator_number': 4,
  'title': 'Implements instructional strategies that actively engage learners',
  'guidelines': '- Employs student-centered strategies that promote participation. - Uses group activities, peer collaboration, and '
                'discussions. - Varies instructional methods (visual, auditory, kinesthetic). - Balances teacher talk with student '
                'interaction. - Designs tasks that require active thinking and doing, not just listening.',
  'evidence_examples': '- Students work in pairs to solve problems and share solutions with the class. - Teacher uses think-pair-share, '
                       'role plays, and cooperative games. - Learners use whiteboards to answer questions simultaneously. - Class '
                       'discussions involve students debating, not only listening to the teacher.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Instruction is lecture-dominated; students are passive and disengaged.',
                         '1': 'Teacher attempts limited strategies but engagement is low; few students participate.',
                         '2': 'Some student-centered strategies are used; engagement varies; limited peer interaction.',
                         '3': 'Teacher uses a variety of strategies (discussion, collaboration, visual aids) that engage most learners.',
                         '4': 'Instructional strategies are consistently active and student-centered; learners are highly engaged and '
                              'participate meaningfully.',
                         '5': 'Strategies are dynamic, innovative, and deeply interactive; learners drive discussions, collaborate, and '
                              'problem-solve independently; engagement is sustained at a high level. Supported by proof: lesson '
                              'observation, student engagement evidence.'}},
 {'domain_key': 'D',
  'domain_title': 'Essentials Dimension',
  'indicator_number': 5,
  'title': 'Manages the learning time in an efficient and optimal manner',
  'guidelines': '- Begins lessons promptly and uses time effectively. - Provides smooth transitions between activities. - Keeps learners '
                'focused with minimal disruptions. - Balances time for explanation, practice, and reflection. - Adjusts pacing flexibly to '
                'maintain learning momentum.',
  'evidence_examples': '- Teacher uses a timer to manage group activity time. - Transitions are efficient: students move from group work '
                       'to whole-class discussion in under a minute. - Minimal time is wasted on non-instructional tasks. - If students '
                       'finish early, teacher has extension tasks ready.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Lesson is disorganized; significant time is lost; objectives are not met.',
                         '1': 'Teacher shows limited ability to manage time; frequent disruptions or long transitions.',
                         '2': 'Some activities run efficiently but time is unevenly managed; pacing is inconsistent.',
                         '3': 'Teacher manages time effectively; transitions are smooth; objectives are mostly achieved within the '
                              'allotted time.',
                         '4': 'Teacher consistently maximizes learning time; pacing is balanced; transitions are efficient; little time is '
                              'wasted.',
                         '5': 'Time management is exemplary; lessons are dynamic yet efficient; transitions are seamless; extension tasks '
                              'ensure all time is used productively. Supported by proof: observation notes, lesson timing records.'}},
 {'domain_key': 'E',
  'domain_title': 'Agency Dimension',
  'indicator_number': 1,
  'title': 'Empowers learners to be responsible for the learning at hand',
  'guidelines': '- Encourages students to take ownership of their work and learning process. - Provides opportunities for independent and '
                'inquiry-based learning. - Guides learners to reflect on their choices and outcomes. - Promotes accountability for '
                'completing tasks. - Models strategies for self-directed learning.',
  'evidence_examples': '- Teacher says: “You are the problem-solvers today; I will only guide.” - Students keep learning journals to track '
                       'their progress. - Learners set their own mini-goals for the lesson. - Students are responsible for collecting and '
                       'submitting their work without reminders.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Teacher takes full control; learners are passive; no ownership of learning.',
                         '1': 'Learners are rarely encouraged to take responsibility; limited opportunities for independence.',
                         '2': 'Some attempts to promote responsibility; few students take initiative.',
                         '3': 'Teacher encourages learners to take responsibility through goal setting or task ownership; most students '
                              'respond positively.',
                         '4': 'Learners are consistently empowered to own their learning; reflection and self-direction are built into '
                              'lessons.',
                         '5': 'Learners demonstrate strong autonomy, self-regulation, and accountability; students track their own goals '
                              'and progress independently. Supported by proof: student reflections, self-assessments, observation notes.'}},
 {'domain_key': 'E',
  'domain_title': 'Agency Dimension',
  'indicator_number': 2,
  'title': 'Gives learners choices about the learning activities or tasks',
  'guidelines': '- Offers options in assignments, projects, or learning methods. - Encourages student voice in decision-making for '
                'activities. - Provides flexibility in how learners demonstrate understanding. - Promotes autonomy while ensuring '
                'objectives are met.',
  'evidence_examples': '- Students choose between writing an essay, creating a poster, or recording a video to show understanding. - '
                       'During reading, students select from a set of leveled texts. - Teacher asks: “Would you like to work individually '
                       'or in pairs on this task?”',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'No choices are given; all students follow the same rigid approach.',
                         '1': 'Minimal choice provided (e.g., choosing partners), but not meaningful to learning.',
                         '2': 'Some opportunities for choice exist but are limited in scope.',
                         '3': 'Teacher provides learners with meaningful options in activities or formats of demonstrating learning.',
                         '4': 'Choices are consistently integrated; learners select tasks that align with their interests, learning '
                              'styles, or strengths.',
                         '5': 'Choice is embedded in classroom culture; learners design parts of their own tasks, projects, or '
                              'assessments; autonomy leads to deeper engagement. Supported by proof: lesson plans with choice options, '
                              'student work samples.'}},
 {'domain_key': 'E',
  'domain_title': 'Agency Dimension',
  'indicator_number': 3,
  'title': 'Provides assistance for learners to navigate and monitor their learning progress',
  'guidelines': '- Teaches strategies for goal setting and self-monitoring. - Provides tools (charts, trackers, apps) for learners to '
                'track growth. - Encourages reflection on strengths and areas for improvement. - Supports learners in identifying and '
                'overcoming challenges.',
  'evidence_examples': '- Students use progress charts to record quiz scores and improvements. - Teacher facilitates short one-on-one '
                       'conferences to discuss learning goals. - Students reflect in journals: “What did I do well today? What can I '
                       'improve?” - Learners use checklists to ensure tasks are completed correctly.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'No guidance on progress; students have no idea how they are performing.',
                         '1': 'Limited feedback or tools are provided for tracking progress.',
                         '2': 'Some strategies (e.g., checklists or reminders) are used, but not consistently.',
                         '3': 'Teacher regularly provides guidance (trackers, reflections, conferences) to help students monitor learning.',
                         '4': 'Monitoring tools and strategies are embedded; learners are supported in reflecting and adjusting their '
                              'efforts.',
                         '5': 'Learners independently track progress, set goals, and reflect on growth; teacher scaffolds advanced '
                              'self-monitoring strategies. Supported by proof: student trackers, progress charts, reflection journals.'}},
 {'domain_key': 'E',
  'domain_title': 'Agency Dimension',
  'indicator_number': 4,
  'title': 'Encourages learners to persevere with or seek challenging activities or tasks',
  'guidelines': '- Promotes resilience by praising effort and persistence. - Provides scaffolding when learners struggle but encourages '
                'them to persist. - Reinforces that mistakes are part of learning. - Challenges students with higher-level tasks when '
                'appropriate.',
  'evidence_examples': '- Teacher says: “This is difficult, but I know you can figure it out—try one more way.” - Students attempt '
                       'challenging math problems even after initial errors. - Learners reflect on how they overcame difficulties in a '
                       'project. - Advanced learners choose extension tasks beyond the core lesson.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Learners are not encouraged to try challenging tasks; mistakes are discouraged.',
                         '1': 'Teacher occasionally acknowledges effort but avoids pushing learners beyond comfort zones.',
                         '2': 'Some encouragement is provided, but learners often give up when tasks are difficult.',
                         '3': 'Teacher promotes resilience by encouraging learners to keep trying and praising effort.',
                         '4': 'Perseverance is consistently encouraged; mistakes are reframed as learning opportunities; challenging tasks '
                              'are normalized.',
                         '5': 'Learners actively embrace challenges, seek out difficult tasks, and persist with enthusiasm; classroom '
                              'culture celebrates resilience and growth. Supported by proof: observation notes, student reflections, work '
                              'samples.'}},
 {'domain_key': 'E',
  'domain_title': 'Agency Dimension',
  'indicator_number': 5,
  'title': 'Builds learners’ growth mindset and self-efficacy',
  'guidelines': '- Encourages positive self-talk and belief in abilities. - Recognizes effort as well as achievement. - Promotes learning '
                'from mistakes rather than fearing them. - Supports long-term goal setting and resilience.',
  'evidence_examples': '- Teacher highlights effort: “I like how you kept trying different methods.” - Students use statements like “I can '
                       'improve with practice” instead of “I’m not good at this.” - Mistakes are analyzed together: “What can we learn '
                       'from this error?” - Learners set long-term goals, such as improving reading fluency by semester’s end.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Teacher conveys fixed mindset messages (e.g., “Some students just can’t do this”).',
                         '1': 'Occasional encouragement but messages reinforce ability over effort.',
                         '2': 'Some growth mindset language is used; students show partial belief in improvement.',
                         '3': 'Teacher consistently reinforces growth mindset language and encourages self-belief; learners show '
                              'confidence in progress.',
                         '4': 'Growth mindset and self-efficacy are strongly cultivated; learners demonstrate confidence and resilience '
                              'when facing challenges.',
                         '5': 'Learners consistently apply growth mindset principles independently; they believe in their abilities, '
                              'support peers, and set ambitious goals. Supported by proof: student reflections, classroom dialogue, '
                              'observation records.'}},
 {'domain_key': 'F',
  'domain_title': 'Relationship Dimension',
  'indicator_number': 1,
  'title': 'Promotes respectful and caring interactions toward and between learners',
  'guidelines': '- Models respect through tone, body language, and choice of words. - Builds positive teacher–student relationships. - '
                'Encourages empathy and kindness in peer interactions. - Addresses disrespect promptly and constructively. - Creates a '
                'classroom culture of trust and mutual care.',
  'evidence_examples': '- Teacher greets students warmly at the door and uses their names. - Students thank each other for contributions '
                       'during group work. - Teacher says: “I appreciate how you explained that politely.” - Any unkind behavior is '
                       'addressed calmly but firmly.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Teacher does not model or encourage respect; interactions may be harsh, dismissive, or negative.',
                         '1': 'Teacher occasionally demonstrates respect, but interactions are inconsistent; negative peer interactions '
                              'are not addressed.',
                         '2': 'Some respectful interactions are encouraged, but not all learners feel valued.',
                         '3': 'Teacher models respectful and caring behavior; learners generally feel safe and supported.',
                         '4': 'Respect and care are consistently modeled and reinforced; classroom culture is positive and trusting.',
                         '5': 'Respect and care are deeply embedded; teacher and students consistently model empathy, kindness, and '
                              'support; learners actively maintain a respectful community. Supported by proof: observation notes, student '
                              'behavior, classroom dialogue.'}},
 {'domain_key': 'F',
  'domain_title': 'Relationship Dimension',
  'indicator_number': 2,
  'title': 'Cultivates learner cooperation, collaboration, and inclusivity',
  'guidelines': '- Designs learning tasks that require teamwork and cooperation. - Ensures inclusive participation from all learners. - '
                'Promotes peer support and shared responsibility. - Encourages learners to value each other’s strengths. - Acts as a '
                'facilitator rather than dominating group work.',
  'evidence_examples': '- Teacher assigns group projects with rotating roles (leader, recorder, presenter). - Students with different '
                       'abilities are paired strategically to support one another. - Learners use cooperative games or problem-solving '
                       'tasks that require teamwork. - Teacher observes groups, guiding only when needed.',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'No evidence of cooperative or inclusive practices; classroom is competitive or isolating.',
                         '1': 'Minimal cooperation or inclusivity is promoted; only a few students participate.',
                         '2': 'Some group work or cooperative learning occurs, but inclusivity is uneven.',
                         '3': 'Teacher promotes cooperation and collaboration through structured group activities; most learners '
                              'participate.',
                         '4': 'Cooperative learning is consistent and inclusive; learners value each other’s strengths and collaborate '
                              'effectively.',
                         '5': 'Collaboration and inclusivity are part of classroom culture; learners take initiative in supporting peers, '
                              'ensuring everyone is included. Supported by proof: group work records, observation notes, student '
                              'reflections.'}},
 {'domain_key': 'F',
  'domain_title': 'Relationship Dimension',
  'indicator_number': 3,
  'title': 'Preserves learners’ dignity while attending to their individual needs',
  'guidelines': '- Provides support discreetly to avoid embarrassment. - Communicates with empathy and maturity when correcting learners. '
                '- Maintains high expectations while offering accommodations. - Protects students from ridicule or negative labeling. - '
                'Ensures every learner feels valued regardless of ability level.',
  'evidence_examples': '- Teacher quietly checks in with a struggling student instead of pointing it out in front of peers. - When '
                       'redirecting behavior, teacher speaks privately or uses non-verbal signals. - Assignments are differentiated '
                       'without making students feel singled out. - Teacher acknowledges effort: “I know this was challenging, but you '
                       'worked hard through it.”',
  'rubric_descriptors': {'NA': 'Not Applicable',
                         '0': 'Learners’ needs are ignored or addressed in a way that embarrasses or singles them out.',
                         '1': 'Teacher attempts to support learners but occasionally compromises their dignity.',
                         '2': 'Some individual support is provided respectfully, but not consistently.',
                         '3': 'Teacher attends to learners’ needs while maintaining their dignity; corrections are discreet and '
                              'respectful.',
                         '4': 'Teacher consistently supports learners with empathy and discretion; individual needs are addressed without '
                              'stigma.',
                         '5': 'Learners’ dignity is central to classroom practice; teacher creates a culture of empathy where peers also '
                              'respect and protect each other’s dignity. Supported by proof: observation notes, teacher-student '
                              'interactions, student feedback.'}}]


OBSERVATION_SCHEMA_COLUMNS = {
    "observation_criteria": {
        "id": "INTEGER",
        "domain_key": "VARCHAR(8) NOT NULL DEFAULT ''",
        "domain_title": "VARCHAR(160) NOT NULL DEFAULT ''",
        "indicator_number": "INTEGER NOT NULL DEFAULT 0",
        "title": "TEXT NOT NULL DEFAULT ''",
        "guidelines": "TEXT NOT NULL DEFAULT ''",
        "evidence_examples": "TEXT NOT NULL DEFAULT ''",
        "rubric_descriptors": "TEXT NOT NULL DEFAULT '{}'",
        "sort_order": "INTEGER NOT NULL DEFAULT 0",
        "is_active": "BOOLEAN NOT NULL DEFAULT TRUE",
    },
    "observations": {
        "id": "INTEGER",
        "branch_id": "INTEGER NOT NULL DEFAULT 0",
        "academic_year_id": "INTEGER NOT NULL DEFAULT 0",
        "teacher_id": "INTEGER NOT NULL DEFAULT 0",
        "evaluator_user_id": "VARCHAR(10) NOT NULL DEFAULT ''",
        "observation_type": "VARCHAR(20) NOT NULL DEFAULT 'Formal'",
        "observation_date": "VARCHAR(10) NOT NULL DEFAULT ''",
        "term": "VARCHAR(20)",
        "grade": "VARCHAR(20)",
        "section": "VARCHAR(20)",
        "period": "VARCHAR(20)",
        "subject": "VARCHAR(120)",
        "status": "VARCHAR(20) NOT NULL DEFAULT 'Final'",
        "overall_score": "VARCHAR(20)",
        "evaluator_notes": "TEXT",
        "evaluatee_notes": "TEXT",
        "teacher_signature_data": "TEXT",
        "evaluator_signature_data": "TEXT",
        "locked_at": "DATETIME",
        "smart_feedback": "TEXT",
        "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "observation_scores": {
        "id": "INTEGER",
        "observation_id": "INTEGER NOT NULL DEFAULT 0",
        "criterion_id": "INTEGER NOT NULL DEFAULT 0",
        "rating": "VARCHAR(4) NOT NULL DEFAULT 'NA'",
        "evidence": "TEXT",
    },
    "observation_self_evaluations": {
        "id": "INTEGER",
        "observation_id": "INTEGER NOT NULL DEFAULT 0",
        "teacher_id": "INTEGER NOT NULL DEFAULT 0",
        "reflection": "TEXT",
        "strengths": "TEXT",
        "growth_areas": "TEXT",
        "support_needed": "TEXT",
        "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "observation_self_evaluation_scores": {
        "id": "INTEGER",
        "self_evaluation_id": "INTEGER NOT NULL DEFAULT 0",
        "criterion_id": "INTEGER NOT NULL DEFAULT 0",
        "rating": "VARCHAR(4) NOT NULL DEFAULT 'NA'",
        "evidence": "TEXT",
    },
}


def ensure_observation_schema():
    models.Base.metadata.create_all(
        bind=engine,
        tables=[
            models.ObservationCriterion.__table__,
            models.Observation.__table__,
            models.ObservationScore.__table__,
            models.ObservationSelfEvaluation.__table__,
            models.ObservationSelfEvaluationScore.__table__,
        ],
    )
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table_name, column_sql_map in OBSERVATION_SCHEMA_COLUMNS.items():
            if table_name not in existing_tables:
                continue
            existing_columns = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            for column_name, column_sql in column_sql_map.items():
                if column_name == "id" or column_name in existing_columns:
                    continue
                logger.warning(
                    "Adding missing Observation schema column %s.%s",
                    table_name,
                    column_name,
                )
                column_sql = _dialect_column_sql(column_sql, engine.dialect.name)
                add_column_prefix = "ADD COLUMN IF NOT EXISTS" if engine.dialect.name == "postgresql" else "ADD COLUMN"
                connection.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        f"{add_column_prefix} {column_name} {column_sql}"
                    )
                )


def _dialect_column_sql(column_sql: str, dialect_name: str) -> str:
    if dialect_name != "postgresql":
        return column_sql
    return column_sql.replace("DATETIME", "TIMESTAMP")


def prepare_observation_module(db: Session):
    ensure_observation_schema()
    ensure_observation_seed_data(db)


def _get_scope_ids(current_user):
    return (
        getattr(current_user, "scope_branch_id", current_user.branch_id),
        getattr(current_user, "scope_academic_year_id", current_user.academic_year_id),
    )


def _teacher_name(teacher) -> str:
    if not teacher:
        return "Unknown Teacher"
    parts = [teacher.first_name, teacher.middle_name, teacher.last_name]
    return " ".join(part for part in parts if part).strip() or f"Teacher #{teacher.id}"


def _user_display_name(user) -> str:
    parts = [
        str(getattr(user, "first_name", "") or "").strip(),
        str(getattr(user, "last_name", "") or "").strip(),
    ]
    return " ".join(part for part in parts if part) or str(getattr(user, "user_id", "") or "Current User")


def _teacher_choice_rows(teachers):
    return [
        {
            "id": teacher.id,
            "teacher_id": teacher.teacher_id or "",
            "name": _teacher_name(teacher),
        }
        for teacher in teachers
    ]


def _subject_choice_rows(subjects, teacher_subject_map=None):
    teacher_subject_map = teacher_subject_map or {}
    rows = []
    for subject in subjects:
        subject_code = str(subject.subject_code or "").strip()
        subject_name = str(subject.subject_name or "").strip()
        grade = str(subject.grade if subject.grade is not None else "").strip()
        assigned_teacher_ids = sorted(
            teacher_id
            for teacher_id, subject_codes in teacher_subject_map.items()
            if subject_code and subject_code in subject_codes
        )
        label_parts = []
        if subject_code:
            label_parts.append(subject_code)
        if subject_name:
            label_parts.append(subject_name)
        label = " - ".join(label_parts) if label_parts else f"Subject #{subject.id}"
        if grade:
            label = f"{label} (Grade {grade})"
        rows.append(
            {
                "value": subject_code or subject_name or label,
                "label": label,
                "subject_code": subject_code,
                "grade": grade,
                "assigned_teacher_ids": ",".join(str(teacher_id) for teacher_id in assigned_teacher_ids),
            }
        )
    return rows


def _teacher_subject_code_map(db: Session, teachers):
    teacher_ids = [teacher.id for teacher in teachers if getattr(teacher, "id", None)]
    subject_map = {
        teacher_id: set()
        for teacher_id in teacher_ids
    }
    if not teacher_ids:
        return subject_map

    allocation_rows = db.query(models.TeacherSubjectAllocation).filter(
        models.TeacherSubjectAllocation.teacher_id.in_(teacher_ids)
    ).all()
    for allocation in allocation_rows:
        code = str(allocation.subject_code or "").strip()
        if code:
            subject_map.setdefault(allocation.teacher_id, set()).add(code)

    for teacher in teachers:
        code = str(getattr(teacher, "subject_code", "") or "").strip()
        if code:
            subject_map.setdefault(teacher.id, set()).add(code)
    return subject_map


def _teacher_section_choice_rows(db: Session, teachers):
    teacher_ids = [teacher.id for teacher in teachers if getattr(teacher, "id", None)]
    section_map = {teacher_id: [] for teacher_id in teacher_ids}
    if not teacher_ids:
        return section_map

    assignment_rows = db.query(
        models.TeacherSectionAssignment.teacher_id,
        models.TeacherSectionAssignment.subject_code,
        models.PlanningSection.id,
        models.PlanningSection.grade_level,
        models.PlanningSection.section_name,
    ).join(
        models.PlanningSection,
        models.PlanningSection.id == models.TeacherSectionAssignment.planning_section_id,
    ).filter(
        models.TeacherSectionAssignment.teacher_id.in_(teacher_ids)
    ).order_by(
        models.PlanningSection.grade_level.asc(),
        models.PlanningSection.section_name.asc(),
    ).all()

    seen = set()
    for teacher_id, subject_code, section_id, grade_level, section_name in assignment_rows:
        key = (teacher_id, section_id)
        if key in seen:
            continue
        seen.add(key)
        grade = str(grade_level or "").strip()
        section = str(section_name or "").strip()
        if not grade or not section:
            continue
        section_map.setdefault(teacher_id, []).append(
            {
                "id": section_id,
                "grade": grade,
                "section": section,
                "label": f"Grade {grade} - {section}",
                "subject_code": str(subject_code or "").strip(),
            }
        )
    return section_map


def _is_teacher_user(current_user) -> bool:
    return auth.normalize_role(getattr(current_user, "role", "")) == auth.ROLE_USER


def _get_current_teacher(db: Session, current_user):
    user_id = str(getattr(current_user, "user_id", "") or "").strip()
    if not user_id:
        return None
    branch_id, academic_year_id = _get_scope_ids(current_user)
    return db.query(models.Teacher).filter(
        models.Teacher.teacher_id == user_id,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).first()


def _can_create_observation(current_user) -> bool:
    return auth.can_modify_data(current_user) and not _is_teacher_user(current_user)


def _can_override_locked_observation(current_user) -> bool:
    role = auth.normalize_role(getattr(current_user, "role", ""))
    return role in {auth.ROLE_DEVELOPER, auth.ROLE_ADMINISTRATOR}


def _observation_is_locked(observation) -> bool:
    return bool(getattr(observation, "locked_at", None) or getattr(observation, "status", "") == "Locked")


def _observation_status_label(observation) -> str:
    if _observation_is_locked(observation):
        return "Finalized & Locked"
    status = str(getattr(observation, "status", "") or "").strip()
    if not status or status == "Final":
        return "Awaiting Teacher Review & Signature"
    return status


def _can_edit_observation(current_user, observation) -> bool:
    if not auth.can_edit_data(current_user) or _is_teacher_user(current_user):
        return False
    return not _observation_is_locked(observation) or _can_override_locked_observation(current_user)


def _can_delete_observation(current_user, observation) -> bool:
    if not auth.can_delete_data(current_user) or _is_teacher_user(current_user):
        return False
    return not _observation_is_locked(observation) or _can_override_locked_observation(current_user)


def _get_self_evaluation_bundle(db: Session, observation):
    if not observation:
        return None, {}
    self_evaluation = db.query(models.ObservationSelfEvaluation).filter(
        models.ObservationSelfEvaluation.observation_id == observation.id
    ).first()
    if not self_evaluation:
        return None, {}
    scores = {
        score.criterion_id: score
        for score in db.query(models.ObservationSelfEvaluationScore).filter(
            models.ObservationSelfEvaluationScore.self_evaluation_id == self_evaluation.id
        ).all()
    }
    return self_evaluation, scores


def _self_evaluation_has_rating(self_scores_by_criterion: dict) -> bool:
    return any(
        str(getattr(score, "rating", "") or "").strip().upper() != "NA"
        for score in self_scores_by_criterion.values()
    )


def _observation_export_state(db: Session, observation) -> dict:
    self_evaluation, self_scores_by_criterion = _get_self_evaluation_bundle(db, observation)
    self_evaluation_complete = bool(
        self_evaluation and _self_evaluation_has_rating(self_scores_by_criterion)
    )
    evaluator_signed = bool(getattr(observation, "evaluator_signature_data", None))
    teacher_signed = bool(getattr(observation, "teacher_signature_data", None))
    locked = _observation_is_locked(observation)
    return {
        "self_evaluation": self_evaluation,
        "self_scores_by_criterion": self_scores_by_criterion,
        "self_evaluation_complete": self_evaluation_complete,
        "evaluator_signed": evaluator_signed,
        "teacher_signed": teacher_signed,
        "locked": locked,
        "can_export": bool(locked and evaluator_signed and teacher_signed and self_evaluation_complete),
    }


def _formal_observations_for_teacher(db: Session, teacher_id: int, branch_id: int, academic_year_id: int):
    return db.query(models.Observation).filter(
        models.Observation.teacher_id == teacher_id,
        models.Observation.branch_id == branch_id,
        models.Observation.academic_year_id == academic_year_id,
        models.Observation.observation_type == "Formal",
    ).order_by(
        models.Observation.observation_date.asc(),
        models.Observation.created_at.asc(),
        models.Observation.id.asc(),
    ).all()


def _teacher_cycle_export_state(db: Session, teacher_id: int, branch_id: int, academic_year_id: int) -> dict:
    formal_observations = _formal_observations_for_teacher(db, teacher_id, branch_id, academic_year_id)
    finalized_observations = [
        observation
        for observation in formal_observations
        if _observation_export_state(db, observation)["can_export"]
    ]
    return {
        "formal_observations": formal_observations,
        "finalized_observations": finalized_observations,
        "formal_count": len(formal_observations),
        "finalized_count": len(finalized_observations),
        "can_export": len(finalized_observations) >= FORMAL_OBSERVATION_TARGET,
    }


def _observation_link(observation_id: int) -> str:
    return f"/observations/{observation_id}"


def _find_teacher_user(db: Session, teacher):
    teacher_user_id = str(getattr(teacher, "teacher_id", "") or "").strip()
    if not teacher_user_id:
        return None
    return db.query(models.User).filter(
        models.User.user_id == teacher_user_id,
        models.User.is_active == True,
    ).first()


def _notification_exists(db: Session, recipient_user_id: str, request_type: str, details: str) -> bool:
    return db.query(models.SystemNotification.id).filter(
        models.SystemNotification.recipient_user_id == recipient_user_id,
        models.SystemNotification.request_type == request_type,
        models.SystemNotification.details == details,
        models.SystemNotification.status != "Resolved",
    ).first() is not None


def _create_observation_notification(
    db: Session,
    recipient_user_id: str,
    requesting_user_id: str,
    title: str,
    message: str,
    details: str,
):
    recipient_user_id = str(recipient_user_id or "").strip()
    if not recipient_user_id:
        return None
    request_type = "Observation"
    if _notification_exists(db, recipient_user_id, request_type, details):
        return None
    notification = models.SystemNotification(
        recipient_user_id=recipient_user_id,
        requesting_user_id=str(requesting_user_id or "").strip(),
        request_type=request_type,
        title=title,
        message=message,
        details=details,
        status="New",
        recipient_scope="User",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(notification)
    logger.warning(
        "OBSERVATION DEBUG notification created recipient=%s requester=%s details=%s",
        recipient_user_id,
        requesting_user_id,
        details,
    )
    return notification


def _notify_teacher_observation_ready(db: Session, teacher, observation, current_user):
    teacher_user = _find_teacher_user(db, teacher)
    if not teacher_user:
        logger.warning(
            "OBSERVATION DEBUG notification skipped no active teacher user teacher_id=%s observation_id=%s",
            getattr(teacher, "teacher_id", ""),
            getattr(observation, "id", ""),
        )
        return None
    link = _observation_link(observation.id)
    return _create_observation_notification(
        db,
        recipient_user_id=teacher_user.user_id,
        requesting_user_id=getattr(current_user, "user_id", ""),
        title="Observation ready for review and signature",
        message=(
            "A new observation has been submitted for your review and signature. "
            f"<a href=\"{link}\">Open observation</a>."
        ),
        details=f"observation:{observation.id}:teacher_signature_required",
    )


def _notify_evaluator_teacher_signed(db: Session, observation, teacher):
    link = _observation_link(observation.id)
    return _create_observation_notification(
        db,
        recipient_user_id=observation.evaluator_user_id,
        requesting_user_id=str(getattr(teacher, "teacher_id", "") or ""),
        title="Teacher signed observation",
        message=(
            f"{_teacher_name(teacher)} signed the observation. The observation is now locked. "
            f"<a href=\"{link}\">Open observation</a>."
        ),
        details=f"observation:{observation.id}:teacher_signed",
    )


def _notify_evaluator_self_evaluation_saved(db: Session, observation, teacher):
    link = _observation_link(observation.id)
    return _create_observation_notification(
        db,
        recipient_user_id=observation.evaluator_user_id,
        requesting_user_id=str(getattr(teacher, "teacher_id", "") or ""),
        title="Teacher completed self-evaluation",
        message=(
            f"{_teacher_name(teacher)} completed the self-evaluation and evaluatee notes. "
            f"<a href=\"{link}\">Open observation</a>."
        ),
        details=f"observation:{observation.id}:self_evaluation_saved",
    )


def ensure_observation_seed_data(db: Session):
    for index, item in enumerate(OBSERVATION_CRITERIA, start=1):
        criterion = db.query(models.ObservationCriterion).filter(
            models.ObservationCriterion.domain_key == item["domain_key"],
            models.ObservationCriterion.indicator_number == item["indicator_number"],
        ).first()
        if not criterion:
            criterion = models.ObservationCriterion(
                domain_key=item["domain_key"],
                indicator_number=item["indicator_number"],
            )
            db.add(criterion)
        criterion.domain_title = item["domain_title"]
        criterion.title = item["title"]
        criterion.guidelines = item["guidelines"]
        criterion.evidence_examples = item["evidence_examples"]
        criterion.rubric_descriptors = json.dumps(
            item["rubric_descriptors"],
            ensure_ascii=False,
        )
        criterion.sort_order = index
        criterion.is_active = True
    active_keys = {
        (item["domain_key"], item["indicator_number"])
        for item in OBSERVATION_CRITERIA
    }
    existing = db.query(models.ObservationCriterion).all()
    for criterion in existing:
        if (criterion.domain_key, criterion.indicator_number) not in active_keys:
            criterion.is_active = False
    db.commit()
    db.commit()


def _normalize_observation_type(value: str) -> str:
    cleaned = " ".join(str(value or "").replace("_", " ").split()).strip().lower()
    if cleaned == "formal":
        return "Formal"
    if cleaned in {"informal", "non formal", "non-formal", "nonformal"}:
        return "Non-formal"
    return "Formal"


def _is_non_formal_observation(observation) -> bool:
    normalized = _normalize_observation_type(getattr(observation, "observation_type", ""))
    return normalized == "Non-formal"


def _context_keys(context: dict) -> list[str]:
    return sorted(key for key in context.keys() if key != "request")


def _minimal_shell_context(notice: str = "") -> dict:
    return {
        "page_title": "Observations",
        "page_icon": "clipboard-check",
        "branch_name": "Debug Branch",
        "academic_year_name": "Debug Year",
        "nav_items": [],
        "can_manage_system_settings": False,
        "available_scope_branches": [],
        "scoped_branch_id": None,
        "user_image_url": "",
        "user_initials": "U",
        "user_name": "Debug User",
        "role_label": "Debug",
        "new_notification_count": 0,
        "notice": notice,
    }


def _observation_debug_html(title: str, lines: list[str], status_code: int = 200):
    body = "\n".join(f"<li>{html.escape(line)}</li>" for line in lines)
    return HTMLResponse(
        content=(
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{html.escape(title)}</title>"
            "<style>body{font-family:Arial,sans-serif;padding:24px;line-height:1.5}"
            "pre{white-space:pre-wrap;background:#f6f8fa;border:1px solid #d0d7de;"
            "padding:12px;border-radius:8px}</style></head><body>"
            f"<h1>{html.escape(title)}</h1><ul>{body}</ul></body></html>"
        ),
        status_code=status_code,
    )


def _observation_error_html(route: str, stage: str, exc: Exception):
    trace = traceback.format_exc()
    logger.error(
        "OBSERVATION DEBUG failed route=%s stage=%s error=%s\n%s",
        route,
        stage,
        repr(exc),
        trace,
    )
    return HTMLResponse(
        content=(
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Observation Diagnostic</title>"
            "<style>body{font-family:Arial,sans-serif;padding:24px;line-height:1.5}"
            "pre{white-space:pre-wrap;background:#fff7ed;border:1px solid #fed7aa;"
            "padding:12px;border-radius:8px}</style></head><body>"
            "<h1>Observation module diagnostic</h1>"
            "<p>The Observation page hit a controlled diagnostic fallback instead of a 500.</p>"
            f"<p><strong>Route:</strong> {html.escape(route)}</p>"
            f"<p><strong>Failing stage:</strong> {html.escape(stage)}</p>"
            f"<p><strong>Exception:</strong> {html.escape(type(exc).__name__)}: {html.escape(str(exc))}</p>"
            f"<pre>{html.escape(trace)}</pre>"
            "</body></html>"
        ),
        status_code=200,
    )


def _log_observation_stage(stage: str, **details):
    detail_text = " ".join(f"{key}={value}" for key, value in details.items())
    logger.warning("OBSERVATION DEBUG stage=%s %s", stage, detail_text)


def _criteria_by_domain(criteria):
    grouped = []
    current = None
    for criterion in criteria:
        key = criterion.domain_key
        if not current or current["domain_key"] != key:
            current = {
                "domain_key": key,
                "domain_title": criterion.domain_title,
                "criteria": [],
            }
            grouped.append(current)
        current["criteria"].append(criterion)
    return grouped


def _compute_scores(score_rows, criteria_by_id):
    numeric_scores = []
    domain_values = defaultdict(list)
    low_items = []
    high_items = []
    for score in score_rows:
        rating = str(score.rating or "NA").strip().upper()
        if rating == "NA" or rating not in RATING_VALUES:
            continue
        value = int(rating)
        criterion = criteria_by_id.get(score.criterion_id)
        if not criterion:
            continue
        numeric_scores.append(value)
        domain_values[criterion.domain_key].append(value)
        item = {
            "criterion": criterion,
            "rating": value,
            "evidence": str(score.evidence or "").strip(),
        }
        if value <= 2:
            low_items.append(item)
        if value >= 4:
            high_items.append(item)

    overall = round(sum(numeric_scores) / len(numeric_scores), 2) if numeric_scores else None
    domains = []
    for domain_key in sorted(domain_values.keys()):
        values = domain_values[domain_key]
        domain_title = next(
            (
                criterion.domain_title
                for criterion in criteria_by_id.values()
                if criterion.domain_key == domain_key
            ),
            domain_key,
        )
        domains.append(
            {
                "domain_key": domain_key,
                "domain_title": domain_title,
                "average": round(sum(values) / len(values), 2),
                "count": len(values),
            }
        )
    return overall, domains, low_items, high_items


def _build_smart_feedback(score_rows, criteria_by_id):
    overall, domains, low_items, high_items = _compute_scores(score_rows, criteria_by_id)
    strongest = sorted(domains, key=lambda item: item["average"], reverse=True)[:2]
    growth = sorted(domains, key=lambda item: item["average"])[:2]
    strengths = [
        f"{item['criterion'].title} was rated {item['rating']}/5."
        for item in sorted(high_items, key=lambda item: item["rating"], reverse=True)[:3]
    ]
    improvements = [
        f"{item['criterion'].title} needs focused support; current rating is {item['rating']}/5."
        for item in sorted(low_items, key=lambda item: item["rating"])[:3]
    ]
    if not strengths:
        strengths = ["No high-scoring criteria were identified yet; continue collecting specific classroom evidence."]
    if not improvements:
        improvements = ["No critical low-scoring criteria were identified in this observation."]

    return {
        "overall": overall,
        "domain_summary": domains,
        "headline": _feedback_headline(overall),
        "strongest_domains": strongest,
        "growth_domains": growth,
        "strengths": strengths,
        "improvements": improvements,
        "next_steps": _next_steps(overall, growth),
    }


def _feedback_headline(overall):
    if overall is None:
        return "Observation completed without scored criteria."
    if overall >= 4.5:
        return "Outstanding practice is evident across the observed lesson."
    if overall >= 3.5:
        return "Strong practice is evident, with clear areas to keep refining."
    if overall >= 2.5:
        return "Developing practice is visible, and targeted coaching will help the teacher move forward."
    return "This observation shows urgent areas for structured support and follow-up."


def _next_steps(overall, growth_domains):
    if overall is None:
        return ["Add ratings and evidence so the system can generate clearer feedback."]
    steps = []
    if growth_domains:
        labels = ", ".join(item["domain_title"] for item in growth_domains)
        steps.append(f"Prioritize coaching around {labels}.")
    if overall < 3:
        steps.append("Schedule a follow-up observation and agree on one immediate classroom action.")
    else:
        steps.append("Preserve the strongest practices and choose one measurable refinement target for the next lesson.")
    return steps


def _rating_level(rating) -> str:
    value = str(rating or "NA").strip().upper()
    return {
        "NA": "Not Applicable",
        "0": "Not Demonstrated",
        "1": "Limited",
        "2": "Developing",
        "3": "Proficient",
        "4": "Strong",
        "5": "Excellent",
    }.get(value, "Not Rated")


def _clean_pdf_text(value, fallback: str = "-") -> str:
    text_value = str(value or "").strip()
    return text_value if text_value else fallback


def _resolve_display_timezone(timezone_name: str):
    raw_timezone = str(timezone_name or "").strip() or DEFAULT_DISPLAY_TIMEZONE
    try:
        return raw_timezone, ZoneInfo(raw_timezone)
    except ZoneInfoNotFoundError:
        if raw_timezone == DEFAULT_DISPLAY_TIMEZONE:
            return raw_timezone, timezone(timedelta(hours=3), name="KSA")
        return DEFAULT_DISPLAY_TIMEZONE, timezone(timedelta(hours=3), name="KSA")


def _request_timezone_name(request: Request | None) -> str:
    raw_timezone = ""
    if request:
        raw_timezone = str(request.cookies.get("tis_timezone", "") or "").strip()
    timezone_name, _ = _resolve_display_timezone(raw_timezone)
    return timezone_name


def _timezone_label(timezone_name: str) -> str:
    if timezone_name == DEFAULT_DISPLAY_TIMEZONE:
        return "KSA"
    return timezone_name


def _format_pdf_datetime(value, timezone_name: str, fallback: str = "-") -> str:
    if not value:
        return fallback
    if isinstance(value, str):
        raw_value = value.strip()
        if not raw_value:
            return fallback
        try:
            parsed_value = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except ValueError:
            return raw_value
    else:
        parsed_value = value
    if not isinstance(parsed_value, datetime):
        return str(value)
    if parsed_value.tzinfo is None:
        parsed_value = parsed_value.replace(tzinfo=timezone.utc)
    resolved_name, target_timezone = _resolve_display_timezone(timezone_name)
    localized_value = parsed_value.astimezone(target_timezone)
    return f"{localized_value.strftime('%d %b %Y %H:%M')} {_timezone_label(resolved_name)}"


def _pdf_markup(value, fallback: str = "-") -> str:
    return html.escape(_clean_pdf_text(value, fallback))


def _logo_static_path(logo: dict) -> str | None:
    relative_path = str((logo or {}).get("path") or "").replace("\\", "/").lstrip("/")
    if not relative_path:
        return None
    local_path = os.path.join(os.getcwd(), "static", *relative_path.split("/"))
    return local_path if os.path.exists(local_path) else None


def _signature_image_flowable(signature_data: str, *, width: int = 190, height: int = 70):
    if not signature_data:
        return None
    try:
        data = str(signature_data or "").strip()
        if "," in data:
            data = data.split(",", 1)[1]
        image_bytes = BytesIO(base64.b64decode(data))
        from reportlab.platypus import Image

        image = Image(image_bytes, width=width, height=height)
        image.hAlign = "LEFT"
        return image
    except Exception:
        return None


def _build_observation_pdf_report(
    request: Request,
    db: Session,
    observation,
    teacher,
    evaluator,
    criteria,
    score_rows,
    self_evaluation,
    self_scores_by_criterion,
    feedback: dict,
) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise RuntimeError("PDF export dependency is not installed. Install reportlab.") from exc

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=32,
        leftMargin=32,
        topMargin=34,
        bottomMargin=34,
        title=f"Observation Report - {_teacher_name(teacher)}",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], fontSize=20, leading=24, textColor=colors.HexColor("#073a7d"), spaceAfter=8))
    styles.add(ParagraphStyle(name="SectionTitle", parent=styles["Heading2"], fontSize=13, leading=16, textColor=colors.HexColor("#073a7d"), spaceBefore=10, spaceAfter=7))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontSize=8.5, leading=11))
    styles.add(ParagraphStyle(name="BodyTiny", parent=styles["BodyText"], fontSize=7.7, leading=9.5))
    styles.add(ParagraphStyle(name="Badge", parent=styles["BodyText"], alignment=TA_CENTER, fontSize=9, leading=11, textColor=colors.HexColor("#027a48")))

    story = []
    branch = db.query(models.Branch).filter(models.Branch.id == observation.branch_id).first()
    school_group = None
    if branch and getattr(branch, "school_group_id", None):
        school_group = db.query(models.SchoolGroup).filter(models.SchoolGroup.id == branch.school_group_id).first()
    school_name = _clean_pdf_text(getattr(school_group, "name", ""), "School")
    branch_name = _clean_pdf_text(getattr(branch, "name", ""), "Branch")
    display_timezone_name = _request_timezone_name(request)
    generated_at_display = _format_pdf_datetime(datetime.now(timezone.utc), display_timezone_name)

    logo_flowables = []
    for logo in get_school_logo_slots(request, db, observation.branch_id, getattr(school_group, "id", None))[:3]:
        logo_path = _logo_static_path(logo)
        if not logo_path:
            continue
        try:
            image = Image(logo_path, width=0.96 * inch, height=0.36 * inch, kind="proportional")
            image.hAlign = "CENTER"
            logo_flowables.append(image)
        except Exception:
            continue
    logo_strip = None
    if logo_flowables:
        logo_strip = Table([logo_flowables], colWidths=[1.02 * inch] * len(logo_flowables), hAlign="RIGHT")
        logo_strip.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))

    header_left = [
        Paragraph("Teacher Observation Report", styles["ReportTitle"]),
        Paragraph(f"{_pdf_markup(school_name)} | {_pdf_markup(branch_name)}", styles["BodySmall"]),
        Paragraph("Finalized & Locked", styles["Badge"]),
    ]
    header_table = Table(
        [[header_left, logo_strip or Paragraph(_pdf_markup(school_name), styles["BodySmall"])]],
        colWidths=[3.7 * inch, 3.3 * inch],
    )
    header_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#d8e2f0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e3ebf6")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f8fbff")),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f8fbff")),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10))

    evaluator_name = _user_display_name(evaluator) if evaluator else _clean_pdf_text(observation.evaluator_user_id)
    info_rows = [
        ["Teacher", _teacher_name(teacher), "Evaluator", evaluator_name],
        ["Subject", _clean_pdf_text(observation.subject), "Grade / Section", f"{_clean_pdf_text(observation.grade)} {_clean_pdf_text(observation.section, '')}".strip()],
        ["Observation Date", _clean_pdf_text(observation.observation_date), "Type / Term", f"{_clean_pdf_text(observation.observation_type)} | {_clean_pdf_text(observation.term)}"],
        ["Overall Score", f"{_clean_pdf_text(observation.overall_score)} / 5", "Finalized", _format_pdf_datetime(observation.locked_at, display_timezone_name)],
    ]
    info_table = Table(info_rows, colWidths=[1.15 * inch, 2.35 * inch, 1.2 * inch, 2.3 * inch])
    info_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#d8e2f0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e3ebf6")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef6ff")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eef6ff")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(info_table)

    score_by_criterion = {score.criterion_id: score for score in score_rows}
    criteria_by_id = {criterion.id: criterion for criterion in criteria}
    overall, domain_summary, _, _ = _compute_scores(score_rows, criteria_by_id)
    story.append(Paragraph("Overall Summary", styles["SectionTitle"]))
    summary_table = Table(
        [["Overall", f"{overall if overall is not None else '-'} / 5"], ["Status", "Completed & Locked"], ["Self-Observation", "Completed"]],
        colWidths=[1.3 * inch, 1.45 * inch],
    )
    summary_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#d8e2f0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e3ebf6")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef6ff")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ]))
    domain_rows = [["Domain", "Average"]]
    for item in domain_summary:
        domain_rows.append([f"{item['domain_key']}. {item['domain_title']}", f"{item['average']} / 5"])
    if len(domain_rows) == 1:
        domain_rows.append(["Domain scores", "-"])
    domain_table = Table(domain_rows, colWidths=[2.6 * inch, 1.15 * inch])
    domain_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#d8e2f0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e3ebf6")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#073a7d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ]))
    story.append(Table([[summary_table, domain_table]], colWidths=[2.9 * inch, 4.05 * inch]))

    story.append(Paragraph("Observation Domains And Evidence", styles["SectionTitle"]))
    for group in _criteria_by_domain(criteria):
        story.append(Paragraph(f"{group['domain_key']}. {group['domain_title']}", styles["SectionTitle"]))
        rows = [["Indicator", "Evaluator", "Teacher", "Evidence / Comments"]]
        for criterion in group["criteria"]:
            evaluator_score = score_by_criterion.get(criterion.id)
            self_score = self_scores_by_criterion.get(criterion.id)
            evaluator_rating = _clean_pdf_text(getattr(evaluator_score, "rating", "NA"), "NA")
            self_rating = _clean_pdf_text(getattr(self_score, "rating", "NA"), "NA")
            rows.append([
                Paragraph(f"{criterion.indicator_number}. {_pdf_markup(criterion.title)}", styles["BodyTiny"]),
                Paragraph(f"<b>{_pdf_markup(evaluator_rating)}</b><br/>{_pdf_markup(_rating_level(evaluator_rating))}", styles["BodyTiny"]),
                Paragraph(f"<b>{_pdf_markup(self_rating)}</b><br/>{_pdf_markup(_rating_level(self_rating))}", styles["BodyTiny"]),
                Paragraph(
                    f"<b>Evaluator evidence:</b> {_pdf_markup(getattr(evaluator_score, 'evidence', ''))}<br/>"
                    f"<b>Teacher self-evidence:</b> {_pdf_markup(getattr(self_score, 'evidence', ''))}",
                    styles["BodyTiny"],
                ),
            ])
        table = Table(rows, colWidths=[2.45 * inch, 0.85 * inch, 0.85 * inch, 2.85 * inch], repeatRows=1)
        table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#d8e2f0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e3ebf6")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f8ff")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (1, 1), (1, -1), colors.HexColor("#eef6ff")),
            ("BACKGROUND", (2, 1), (2, -1), colors.HexColor("#fff7ed")),
        ]))
        story.append(table)
        story.append(Spacer(1, 5))

    story.append(Paragraph("Evaluator Notes", styles["SectionTitle"]))
    story.append(Paragraph(_pdf_markup(observation.evaluator_notes), styles["BodySmall"]))
    story.append(Paragraph("Teacher Self-Reflection And Evaluatee Notes", styles["SectionTitle"]))
    story.append(Paragraph(_pdf_markup(getattr(self_evaluation, "reflection", None) or observation.evaluatee_notes), styles["BodySmall"]))

    if feedback:
        story.append(Paragraph("Smart Feedback", styles["SectionTitle"]))
        story.append(Paragraph(_pdf_markup(feedback.get("headline")), styles["BodySmall"]))
        feedback_rows = [["Strengths", "Growth Opportunities", "Recommended Next Steps"]]
        feedback_rows.append([
            Paragraph("<br/>".join(_pdf_markup(item) for item in feedback.get("strengths", [])[:4]) or "-", styles["BodyTiny"]),
            Paragraph("<br/>".join(_pdf_markup(item) for item in feedback.get("improvements", [])[:4]) or "-", styles["BodyTiny"]),
            Paragraph("<br/>".join(_pdf_markup(item) for item in feedback.get("next_steps", [])[:4]) or "-", styles["BodyTiny"]),
        ])
        feedback_table = Table(feedback_rows, colWidths=[2.25 * inch, 2.25 * inch, 2.25 * inch])
        feedback_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#d8e2f0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e3ebf6")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#073a7d")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(feedback_table)

    evaluator_signature = _signature_image_flowable(observation.evaluator_signature_data)
    teacher_signature = _signature_image_flowable(observation.teacher_signature_data)
    signature_rows = [
        ["Evaluator Signature", "Teacher Signature"],
        [evaluator_signature or Paragraph("Signature on file", styles["BodySmall"]), teacher_signature or Paragraph("Signature on file", styles["BodySmall"])],
        [
            f"Signed: {_format_pdf_datetime(observation.updated_at, display_timezone_name)}",
            f"Signed and locked: {_format_pdf_datetime(observation.locked_at, display_timezone_name)}",
        ],
    ]
    signature_table = Table(signature_rows, colWidths=[3.45 * inch, 3.45 * inch])
    signature_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#d8e2f0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e3ebf6")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fbff")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ]))
    story.append(Paragraph("Signatures And Acknowledgment", styles["SectionTitle"]))
    story.append(signature_table)
    story.append(Paragraph(
        "This report is generated from a locked observation record after evaluator submission, teacher self-observation, and both digital signatures.",
        styles["BodyTiny"],
    ))

    def _draw_footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 32)
        canvas.setFillColor(colors.HexColor("#eef6ff"))
        canvas.translate(300, 410)
        canvas.rotate(35)
        canvas.drawCentredString(0, 0, "FINALIZED & LOCKED")
        canvas.restoreState()
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#48607f"))
        canvas.drawString(32, 18, f"Generated by TIS on {generated_at_display}")
        canvas.drawRightString(563, 18, f"Page {doc_obj.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buffer.getvalue()


def _build_teacher_cycle_pdf_report(
    request: Request,
    db: Session,
    teacher,
    observations,
    criteria,
) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise RuntimeError("PDF export dependency is not installed. Install reportlab.") from exc

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=32,
        bottomMargin=32,
        title=f"Observation Progress Report - {_teacher_name(teacher)}",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CycleTitle", parent=styles["Title"], fontSize=19, leading=23, textColor=colors.HexColor("#073a7d"), spaceAfter=7))
    styles.add(ParagraphStyle(name="SectionTitle", parent=styles["Heading2"], fontSize=13, leading=16, textColor=colors.HexColor("#073a7d"), spaceBefore=10, spaceAfter=7))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontSize=8.2, leading=10.5))
    styles.add(ParagraphStyle(name="BodyTiny", parent=styles["BodyText"], fontSize=7.2, leading=8.8))
    styles.add(ParagraphStyle(name="Badge", parent=styles["BodyText"], alignment=TA_CENTER, fontSize=9, leading=11, textColor=colors.HexColor("#027a48")))

    first_observation = observations[0]
    branch = db.query(models.Branch).filter(models.Branch.id == first_observation.branch_id).first()
    school_group = None
    if branch and getattr(branch, "school_group_id", None):
        school_group = db.query(models.SchoolGroup).filter(models.SchoolGroup.id == branch.school_group_id).first()
    school_name = _clean_pdf_text(getattr(school_group, "name", ""), "School")
    branch_name = _clean_pdf_text(getattr(branch, "name", ""), "Branch")
    display_timezone_name = _request_timezone_name(request)
    generated_at_display = _format_pdf_datetime(datetime.now(timezone.utc), display_timezone_name)

    logo_flowables = []
    for logo in get_school_logo_slots(request, db, first_observation.branch_id, getattr(school_group, "id", None))[:3]:
        logo_path = _logo_static_path(logo)
        if not logo_path:
            continue
        try:
            logo_image = Image(logo_path, width=0.96 * inch, height=0.36 * inch, kind="proportional")
            logo_image.hAlign = "CENTER"
            logo_flowables.append(logo_image)
        except Exception:
            continue
    logo_strip = None
    if logo_flowables:
        logo_strip = Table([logo_flowables], colWidths=[1.02 * inch] * len(logo_flowables), hAlign="RIGHT")
        logo_strip.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))

    story = []
    formal_count = sum(
        1
        for observation in observations
        if _normalize_observation_type(observation.observation_type) == "Formal"
    )
    finalized_count = sum(1 for observation in observations if _observation_is_locked(observation))
    cycle_status = "Completed" if formal_count >= FORMAL_OBSERVATION_TARGET else "In Progress"
    header_left = [
        Paragraph("Teacher Observation Progress Report", styles["CycleTitle"]),
        Paragraph(f"{_pdf_markup(school_name)} | {_pdf_markup(branch_name)}", styles["BodySmall"]),
        Paragraph(f"{len(observations)} Observations Recorded | {formal_count} / {FORMAL_OBSERVATION_TARGET} Formal", styles["Badge"]),
    ]
    header_table = Table(
        [[header_left, logo_strip or Paragraph(_pdf_markup(school_name), styles["BodySmall"])]],
        colWidths=[3.75 * inch, 3.2 * inch],
    )
    header_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#d8e2f0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e3ebf6")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f8fbff")),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 9))

    scores = []
    for observation in observations:
        try:
            scores.append(float(str(observation.overall_score or "").strip()))
        except ValueError:
            continue
    average = round(sum(scores) / len(scores), 2) if scores else None
    percentage = round((average / 5) * 100) if average is not None else None
    summary_rows = [
        ["Teacher", _teacher_name(teacher), "Formal Observations", f"{formal_count} / {FORMAL_OBSERVATION_TARGET}"],
        ["Average Score", f"{average if average is not None else '-'} / 5", "Percentage", f"{percentage if percentage is not None else '-'}%"],
        ["Cycle Status", cycle_status, "Finalized & Locked", str(finalized_count)],
        ["Generated", generated_at_display, "All Records", str(len(observations))],
    ]
    summary_table = Table(summary_rows, colWidths=[1.2 * inch, 2.3 * inch, 1.35 * inch, 2.1 * inch])
    summary_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#d8e2f0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e3ebf6")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef6ff")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eef6ff")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.2),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(summary_table)

    story.append(Paragraph("Observation Cycle Summary", styles["SectionTitle"]))
    overview_rows = [["#", "Type", "Date", "Subject", "Evaluator", "Score", "Status"]]
    for index, observation in enumerate(observations, start=1):
        evaluator = db.query(models.User).filter(models.User.user_id == observation.evaluator_user_id).first()
        overview_rows.append([
            str(index),
            _normalize_observation_type(observation.observation_type),
            _clean_pdf_text(observation.observation_date),
            _clean_pdf_text(observation.subject),
            _user_display_name(evaluator) if evaluator else _clean_pdf_text(observation.evaluator_user_id),
            f"{_clean_pdf_text(observation.overall_score)} / 5",
            _observation_status_label(observation),
        ])
    overview_table = Table(overview_rows, colWidths=[0.28 * inch, 0.67 * inch, 0.72 * inch, 0.95 * inch, 1.3 * inch, 0.55 * inch, 2.0 * inch], repeatRows=1)
    overview_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#d8e2f0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e3ebf6")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#073a7d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.2),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(overview_table)

    criteria_by_id = {criterion.id: criterion for criterion in criteria}
    for index, observation in enumerate(observations, start=1):
        story.append(Paragraph(
            f"Observation {index}: {_normalize_observation_type(observation.observation_type)} | "
            f"{_clean_pdf_text(observation.observation_date)} | {_pdf_markup(observation.subject)}",
            styles["SectionTitle"],
        ))
        score_rows = db.query(models.ObservationScore).filter(
            models.ObservationScore.observation_id == observation.id
        ).all()
        scores_by_criterion = {score.criterion_id: score for score in score_rows}
        detail_rows = [["Domain", "Indicator", "Rating", "Evidence"]]
        for criterion in criteria:
            score = scores_by_criterion.get(criterion.id)
            rating = _clean_pdf_text(getattr(score, "rating", "NA"), "NA")
            detail_rows.append([
                _clean_pdf_text(criterion.domain_key),
                Paragraph(f"{criterion.indicator_number}. {_pdf_markup(criterion.title)}", styles["BodyTiny"]),
                Paragraph(f"<b>{_pdf_markup(rating)}</b><br/>{_pdf_markup(_rating_level(rating))}", styles["BodyTiny"]),
                Paragraph(_pdf_markup(getattr(score, "evidence", "")), styles["BodyTiny"]),
            ])
        detail_table = Table(detail_rows, colWidths=[0.55 * inch, 2.65 * inch, 0.85 * inch, 2.95 * inch], repeatRows=1)
        detail_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#d8e2f0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e3ebf6")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f8ff")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.1),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(detail_table)
        if observation.evaluator_notes:
            story.append(Paragraph(f"<b>Evaluator notes:</b> {_pdf_markup(observation.evaluator_notes)}", styles["BodySmall"]))
        if observation.evaluatee_notes:
            story.append(Paragraph(f"<b>Teacher notes:</b> {_pdf_markup(observation.evaluatee_notes)}", styles["BodySmall"]))
        story.append(Spacer(1, 4))

    def _draw_footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 30)
        canvas.setFillColor(colors.HexColor("#eef6ff"))
        canvas.translate(300, 410)
        canvas.rotate(35)
        canvas.drawCentredString(0, 0, "OBSERVATION PROGRESS REPORT")
        canvas.restoreState()
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#48607f"))
        canvas.drawString(30, 18, f"Generated by TIS on {generated_at_display}")
        canvas.drawRightString(565, 18, f"Page {doc_obj.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buffer.getvalue()


def _teacher_observation_access_filter(query, db, current_user):
    if not _is_teacher_user(current_user):
        return query
    teacher = _get_current_teacher(db, current_user)
    if not teacher:
        return query.filter(models.Observation.id == -1)
    return query.filter(models.Observation.teacher_id == teacher.id)


@router.get("")
@router.get("/")
def observations_page(request: Request, db: Session = Depends(get_db)):
    route = str(request.url.path)
    debug_stage = str(request.query_params.get("debug_stage", "") or "").strip().lower()
    stage = "1_route_minimal"
    try:
        _log_observation_stage(stage, route=route)
        if debug_stage in {"1", "route", "minimal"}:
            return _observation_debug_html(
                "Observation module loaded",
                ["Stage 1 passed: /observations route is registered and reachable."],
            )

        stage = "2_template_no_database"
        template_context = {
            "request": request,
            "shell": _minimal_shell_context(),
            "rows": [],
            "can_create": False,
            "target": FORMAL_OBSERVATION_TARGET,
            "has_observations": False,
            "summary": {
                "teachers": 0,
                "total_formal": 0,
                "total_non_formal": 0,
                "total_required": 0,
                "completion_pct": 0,
            },
        }
        templates.env.get_template("observations.html").render(template_context)
        _log_observation_stage(stage, template="observations.html", keys=_context_keys(template_context))
        if debug_stage in {"2", "template"}:
            return templates.TemplateResponse(request, "observations.html", template_context)

        stage = "3_current_user_session"
        current_user = get_current_user(request, db)
        if not current_user:
            _log_observation_stage(stage, authenticated=False)
            return RedirectResponse(url="/")
        branch_id, academic_year_id = _get_scope_ids(current_user)
        _log_observation_stage(
            stage,
            authenticated=True,
            user_id=getattr(current_user, "user_id", ""),
            role=auth.normalize_role(getattr(current_user, "role", "")),
            branch_id=branch_id,
            academic_year_id=academic_year_id,
        )
        if debug_stage in {"3", "user", "session"}:
            return _observation_debug_html(
                "Observation user/session loaded",
                [
                    f"User ID: {getattr(current_user, 'user_id', '')}",
                    f"Role: {auth.normalize_role(getattr(current_user, 'role', ''))}",
                    f"Branch ID: {branch_id}",
                    f"Academic year ID: {academic_year_id}",
                ],
            )

        stage = "4_teacher_list"
        prepare_observation_module(db)
        teachers_query = db.query(models.Teacher).filter(
            models.Teacher.branch_id == branch_id,
            models.Teacher.academic_year_id == academic_year_id,
        )
        teachers = teachers_query.order_by(
            models.Teacher.first_name.asc(),
            models.Teacher.last_name.asc(),
        ).all()
        _log_observation_stage(stage, teachers=len(teachers))
        if debug_stage in {"4", "teachers"}:
            return _observation_debug_html(
                "Observation teacher list loaded",
                [f"Teachers loaded: {len(teachers)}"],
            )

        stage = "5_observation_records"
        observation_rows = db.query(models.Observation).filter(
            models.Observation.branch_id == branch_id,
            models.Observation.academic_year_id == academic_year_id,
        ).all()
        _log_observation_stage(stage, observations=len(observation_rows))
        if debug_stage in {"5", "observations", "records"}:
            return _observation_debug_html(
                "Observation records loaded",
                [f"Observation records loaded: {len(observation_rows)}"],
            )

        stage = "6_formal_non_formal_logic"
        observations_by_teacher = defaultdict(list)
        for observation in observation_rows:
            observations_by_teacher[observation.teacher_id].append(observation)

        rows = []
        for teacher in teachers:
            teacher_observations = observations_by_teacher.get(teacher.id, [])
            formal_count = sum(
                1
                for item in teacher_observations
                if _normalize_observation_type(item.observation_type) == "Formal"
            )
            non_formal_count = sum(
                1 for item in teacher_observations if _is_non_formal_observation(item)
            )
            scored = [
                float(item.overall_score)
                for item in teacher_observations
                if str(item.overall_score or "").replace(".", "", 1).isdigit()
            ]
            latest = sorted(
                teacher_observations,
                key=lambda item: item.observation_date or "",
                reverse=True,
            )
            cycle_export_state = _teacher_cycle_export_state(db, teacher.id, branch_id, academic_year_id)
            rows.append(
                {
                    "teacher": teacher,
                    "teacher_name": _teacher_name(teacher),
                    "formal_count": formal_count,
                    "non_formal_count": non_formal_count,
                    "remaining_formal": max(FORMAL_OBSERVATION_TARGET - formal_count, 0),
                    "progress_pct": min(round((formal_count / FORMAL_OBSERVATION_TARGET) * 100), 100),
                    "average_score": round(sum(scored) / len(scored), 2) if scored else None,
                    "latest": latest[0] if latest else None,
                    "can_edit_latest": _can_edit_observation(current_user, latest[0]) if latest else False,
                    "can_delete_latest": _can_delete_observation(current_user, latest[0]) if latest else False,
                    "can_export_cycle": bool(cycle_export_state.get("can_export")),
                    "cycle_export_count": cycle_export_state.get("finalized_count", 0),
                }
            )
        total_formal = sum(row["formal_count"] for row in rows)
        total_non_formal = sum(row["non_formal_count"] for row in rows)
        total_required = len(rows) * FORMAL_OBSERVATION_TARGET
        _log_observation_stage(
            stage,
            rows=len(rows),
            total_formal=total_formal,
            total_non_formal=total_non_formal,
            total_required=total_required,
        )
        if debug_stage in {"6", "counts", "logic"}:
            return _observation_debug_html(
                "Observation count logic loaded",
                [
                    f"Rows built: {len(rows)}",
                    f"Formal observations: {total_formal}",
                    f"Non-formal observations: {total_non_formal}",
                    f"Formal target required: {total_required}",
                ],
            )

        stage = "7_criteria_evidence"
        criteria = db.query(models.ObservationCriterion).filter(
            models.ObservationCriterion.is_active == True
        ).order_by(models.ObservationCriterion.sort_order.asc()).all()
        criteria_groups = _criteria_by_domain(criteria)
        subjects = db.query(models.Subject).filter(
            models.Subject.branch_id == branch_id,
            models.Subject.academic_year_id == academic_year_id,
        ).order_by(
            models.Subject.grade.asc(),
            models.Subject.subject_code.asc(),
            models.Subject.subject_name.asc(),
        ).all()
        teacher_subject_map = _teacher_subject_code_map(db, teachers)
        teacher_section_map = _teacher_section_choice_rows(db, teachers)
        _log_observation_stage(
            stage,
            criteria=len(criteria),
            groups=len(criteria_groups),
            subjects=len(subjects),
        )
        if debug_stage in {"7", "criteria", "evidence"}:
            return _observation_debug_html(
                "Observation criteria loaded",
                [
                    f"Criteria loaded: {len(criteria)}",
                    f"Criteria groups loaded: {len(criteria_groups)}",
                    f"Subjects loaded: {len(subjects)}",
                ],
            )

        stage = "8_role_permissions_teacher_access"
        if _is_teacher_user(current_user):
            current_teacher = _get_current_teacher(db, current_user)
            allowed_teacher_id = current_teacher.id if current_teacher else -1
            rows = [
                row for row in rows
                if getattr(row["teacher"], "id", None) == allowed_teacher_id
            ]
            observation_rows = [
                observation for observation in observation_rows
                if observation.teacher_id == allowed_teacher_id
            ]
            total_formal = sum(row["formal_count"] for row in rows)
            total_non_formal = sum(row["non_formal_count"] for row in rows)
            total_required = len(rows) * FORMAL_OBSERVATION_TARGET
        can_create = _can_create_observation(current_user)
        shell_context = build_shell_context(
            request,
            db,
            current_user,
            page_key="observations",
            notice=request.query_params.get("notice", ""),
        )
        _log_observation_stage(
            stage,
            role=auth.normalize_role(getattr(current_user, "role", "")),
            can_create=can_create,
            visible_rows=len(rows),
            visible_observations=len(observation_rows),
        )
        if debug_stage in {"8", "permissions", "access"}:
            return _observation_debug_html(
                "Observation permissions loaded",
                [
                    f"Role: {auth.normalize_role(getattr(current_user, 'role', ''))}",
                    f"Can create: {can_create}",
                    f"Visible rows: {len(rows)}",
                    f"Visible observations: {len(observation_rows)}",
                ],
            )

        stage = "9_final_template"
        context = {
            "request": request,
            "rows": rows,
            "can_create": can_create,
            "target": FORMAL_OBSERVATION_TARGET,
            "has_observations": bool(observation_rows),
            "summary": {
                "teachers": len(rows),
                "total_formal": total_formal,
                "total_non_formal": total_non_formal,
                "total_required": total_required,
                "completion_pct": round((total_formal / total_required) * 100) if total_required else 0,
            },
            "teachers": _teacher_choice_rows(teachers),
            "subjects": _subject_choice_rows(subjects, teacher_subject_map),
            "teacher_sections": {str(key): value for key, value in teacher_section_map.items()},
            "criteria_groups": criteria_groups,
            "today": date.today().isoformat(),
            "selected_teacher_id": None,
            "evaluator_display_name": _user_display_name(current_user),
            **shell_context,
        }
        templates.env.get_template("observations.html").render(context)
        _log_observation_stage(stage, template="observations.html", keys=_context_keys(context))
        return templates.TemplateResponse(request, "observations.html", context)
    except Exception as exc:
        return _observation_error_html(route, stage, exc)


@router.get("/new")
def new_observation_page(request: Request, teacher_id: int | None = None, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")
    if not _can_create_observation(current_user):
        return RedirectResponse(url="/observations")

    prepare_observation_module(db)
    branch_id, academic_year_id = _get_scope_ids(current_user)
    teachers = db.query(models.Teacher).filter(
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).order_by(models.Teacher.first_name.asc(), models.Teacher.last_name.asc()).all()
    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).order_by(
        models.Subject.grade.asc(),
        models.Subject.subject_code.asc(),
        models.Subject.subject_name.asc(),
    ).all()
    teacher_subject_map = _teacher_subject_code_map(db, teachers)
    teacher_section_map = _teacher_section_choice_rows(db, teachers)
    criteria = db.query(models.ObservationCriterion).filter(
        models.ObservationCriterion.is_active == True
    ).order_by(models.ObservationCriterion.sort_order.asc()).all()

    return templates.TemplateResponse(
        request,
        "observation_form.html",
        {
            "request": request,
            **build_shell_context(
                request,
                db,
                current_user,
                page_key="observations",
                notice=request.query_params.get("notice", ""),
            ),
            "teachers": _teacher_choice_rows(teachers),
            "subjects": _subject_choice_rows(subjects, teacher_subject_map),
            "teacher_sections": {str(key): value for key, value in teacher_section_map.items()},
            "criteria_groups": _criteria_by_domain(criteria),
            "today": date.today().isoformat(),
            "selected_teacher_id": teacher_id,
            "evaluator_display_name": _user_display_name(current_user),
            "modal_mode": str(request.query_params.get("modal", "") or "") == "1",
        },
    )


@router.post("/")
async def create_observation(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")
    if not _can_create_observation(current_user):
        return RedirectResponse(url="/observations")

    prepare_observation_module(db)
    form = await request.form()
    branch_id, academic_year_id = _get_scope_ids(current_user)
    teacher_pk = _parse_int(form.get("teacher_id"))
    teacher = db.query(models.Teacher).filter(
        models.Teacher.id == teacher_pk,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).first()
    if not teacher:
        return RedirectResponse(url="/observations/new?notice=Select+a+valid+teacher.", status_code=302)

    observation_type = _normalize_observation_type(form.get("observation_type"))
    if observation_type == "Formal":
        formal_count = db.query(models.Observation).filter(
            models.Observation.teacher_id == teacher.id,
            models.Observation.branch_id == branch_id,
            models.Observation.academic_year_id == academic_year_id,
            models.Observation.observation_type == "Formal",
        ).count()
        if formal_count >= FORMAL_OBSERVATION_TARGET:
            return RedirectResponse(
                url=(
                    "/observations/new?"
                    f"teacher_id={teacher.id}&"
                    "notice=This+teacher+already+has+6+formal+observations+for+the+year."
                ),
                status_code=302,
            )
    evaluator_signature_data = str(form.get("evaluator_signature_data") or "").strip()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    observation = models.Observation(
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        teacher_id=teacher.id,
        evaluator_user_id=current_user.user_id,
        observation_type=observation_type,
        observation_date=str(form.get("observation_date") or date.today().isoformat())[:10],
        term=str(form.get("term") or "").strip(),
        grade=str(form.get("grade") or "").strip(),
        section=str(form.get("section") or "").strip(),
        period=str(form.get("period") or "").strip(),
        subject=str(form.get("subject") or "").strip(),
        status="Final",
        evaluator_notes=str(form.get("evaluator_notes") or "").strip(),
        evaluatee_notes="",
        teacher_signature_data="",
        evaluator_signature_data=evaluator_signature_data,
        locked_at=None,
    )
    db.add(observation)
    db.flush()

    criteria = db.query(models.ObservationCriterion).filter(
        models.ObservationCriterion.is_active == True
    ).order_by(models.ObservationCriterion.sort_order.asc()).all()
    score_rows = []
    for criterion in criteria:
        raw_rating = str(form.get(f"rating_{criterion.id}") or "NA").strip().upper()
        rating = raw_rating if raw_rating == "NA" or raw_rating in RATING_VALUES else "NA"
        score = models.ObservationScore(
            observation_id=observation.id,
            criterion_id=criterion.id,
            rating=rating,
            evidence=str(form.get(f"evidence_{criterion.id}") or "").strip(),
        )
        score_rows.append(score)
        db.add(score)

    criteria_by_id = {criterion.id: criterion for criterion in criteria}
    feedback = _build_smart_feedback(score_rows, criteria_by_id)
    observation.overall_score = "" if feedback["overall"] is None else str(feedback["overall"])
    observation.smart_feedback = json.dumps(feedback)
    observation.updated_at = now
    if observation.evaluator_signature_data:
        _notify_teacher_observation_ready(db, teacher, observation, current_user)
    db.commit()

    if str(form.get("modal_mode") or "") == "1":
        return HTMLResponse(
            content=(
                "<!doctype html><html><body>"
                "<script>"
                "window.parent.postMessage({type:'observation-created'}, '*');"
                "</script>"
                "Observation saved."
                "</body></html>"
            )
        )
    return RedirectResponse(url=f"/observations/{observation.id}", status_code=302)


@router.get("/{observation_id}/edit")
def edit_observation_page(observation_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    observation = db.query(models.Observation).filter(models.Observation.id == observation_id).first()
    if not observation or not _can_edit_observation(current_user, observation):
        return RedirectResponse(url="/observations")

    prepare_observation_module(db)
    branch_id, academic_year_id = _get_scope_ids(current_user)
    teachers = db.query(models.Teacher).filter(
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).order_by(models.Teacher.first_name.asc(), models.Teacher.last_name.asc()).all()
    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).order_by(models.Subject.grade.asc(), models.Subject.subject_code.asc(), models.Subject.subject_name.asc()).all()
    criteria = db.query(models.ObservationCriterion).filter(
        models.ObservationCriterion.is_active == True
    ).order_by(models.ObservationCriterion.sort_order.asc()).all()
    score_rows = db.query(models.ObservationScore).filter(
        models.ObservationScore.observation_id == observation.id
    ).all()
    teacher_subject_map = _teacher_subject_code_map(db, teachers)
    teacher_section_map = _teacher_section_choice_rows(db, teachers)

    return templates.TemplateResponse(
        request,
        "observation_form.html",
        {
            "request": request,
            **build_shell_context(request, db, current_user, page_key="observations", notice=request.query_params.get("notice", "")),
            "teachers": _teacher_choice_rows(teachers),
            "subjects": _subject_choice_rows(subjects, teacher_subject_map),
            "teacher_sections": {str(key): value for key, value in teacher_section_map.items()},
            "criteria_groups": _criteria_by_domain(criteria),
            "scores_by_criterion": {score.criterion_id: score for score in score_rows},
            "today": observation.observation_date or date.today().isoformat(),
            "selected_teacher_id": observation.teacher_id,
            "evaluator_display_name": _user_display_name(current_user),
            "modal_mode": str(request.query_params.get("modal", "") or "") == "1",
            "observation": observation,
            "form_action": f"/observations/{observation.id}/edit",
        },
    )


@router.post("/{observation_id}/edit")
async def update_observation(observation_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    observation = db.query(models.Observation).filter(models.Observation.id == observation_id).first()
    if not observation or not _can_edit_observation(current_user, observation):
        return RedirectResponse(url="/observations")

    prepare_observation_module(db)
    form = await request.form()
    branch_id, academic_year_id = _get_scope_ids(current_user)
    teacher_pk = _parse_int(form.get("teacher_id"))
    teacher = db.query(models.Teacher).filter(
        models.Teacher.id == teacher_pk,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).first()
    if not teacher:
        return RedirectResponse(url=f"/observations/{observation.id}/edit?notice=Select+a+valid+teacher.", status_code=302)

    observation.teacher_id = teacher.id
    observation.observation_type = _normalize_observation_type(form.get("observation_type"))
    observation.observation_date = str(form.get("observation_date") or date.today().isoformat())[:10]
    observation.term = str(form.get("term") or "").strip()
    observation.grade = str(form.get("grade") or "").strip()
    observation.section = str(form.get("section") or "").strip()
    observation.period = str(form.get("period") or "").strip()
    observation.subject = str(form.get("subject") or "").strip()
    observation.evaluator_notes = str(form.get("evaluator_notes") or "").strip()
    had_evaluator_signature = bool(observation.evaluator_signature_data)
    evaluator_signature_data = str(form.get("evaluator_signature_data") or "").strip()
    if evaluator_signature_data:
        observation.evaluator_signature_data = evaluator_signature_data

    criteria = db.query(models.ObservationCriterion).filter(
        models.ObservationCriterion.is_active == True
    ).order_by(models.ObservationCriterion.sort_order.asc()).all()
    existing_scores = {
        score.criterion_id: score
        for score in db.query(models.ObservationScore).filter(models.ObservationScore.observation_id == observation.id).all()
    }
    score_rows = []
    for criterion in criteria:
        raw_rating = str(form.get(f"rating_{criterion.id}") or "NA").strip().upper()
        rating = raw_rating if raw_rating == "NA" or raw_rating in RATING_VALUES else "NA"
        score = existing_scores.get(criterion.id)
        if not score:
            score = models.ObservationScore(observation_id=observation.id, criterion_id=criterion.id)
            db.add(score)
        score.rating = rating
        score.evidence = str(form.get(f"evidence_{criterion.id}") or "").strip()
        score_rows.append(score)

    feedback = _build_smart_feedback(score_rows, {criterion.id: criterion for criterion in criteria})
    observation.overall_score = "" if feedback["overall"] is None else str(feedback["overall"])
    observation.smart_feedback = json.dumps(feedback)
    observation.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if observation.evaluator_signature_data and not had_evaluator_signature:
        _notify_teacher_observation_ready(db, teacher, observation, current_user)
    db.commit()

    if str(form.get("modal_mode") or "") == "1":
        return HTMLResponse("<script>window.parent.postMessage({type:'observation-created'}, '*');</script>Observation saved.")
    return RedirectResponse(url=f"/observations/{observation.id}?notice=Observation+updated", status_code=302)


@router.post("/{observation_id}/delete")
async def delete_observation(observation_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")
    observation = db.query(models.Observation).filter(models.Observation.id == observation_id).first()
    if not observation or not _can_delete_observation(current_user, observation):
        return RedirectResponse(url="/observations")
    db.query(models.ObservationScore).filter(models.ObservationScore.observation_id == observation.id).delete()
    self_eval_ids = [
        row.id
        for row in db.query(models.ObservationSelfEvaluation.id).filter(
            models.ObservationSelfEvaluation.observation_id == observation.id
        ).all()
    ]
    if self_eval_ids:
        db.query(models.ObservationSelfEvaluationScore).filter(
            models.ObservationSelfEvaluationScore.self_evaluation_id.in_(self_eval_ids)
        ).delete(synchronize_session=False)
    db.query(models.ObservationSelfEvaluation).filter(models.ObservationSelfEvaluation.observation_id == observation.id).delete()
    db.delete(observation)
    db.commit()
    return RedirectResponse(url="/observations?notice=Observation+deleted", status_code=302)


@router.get("/teacher/{teacher_id}/export/pdf")
def export_teacher_observation_cycle_pdf(teacher_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    branch_id, academic_year_id = _get_scope_ids(current_user)
    teacher = db.query(models.Teacher).filter(
        models.Teacher.id == teacher_id,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).first()
    if not teacher:
        return RedirectResponse(url="/observations")
    if _is_teacher_user(current_user):
        current_teacher = _get_current_teacher(db, current_user)
        if not current_teacher or current_teacher.id != teacher.id:
            return RedirectResponse(url="/observations")

    observations = db.query(models.Observation).filter(
        models.Observation.teacher_id == teacher.id,
        models.Observation.branch_id == branch_id,
        models.Observation.academic_year_id == academic_year_id,
    ).order_by(
        models.Observation.observation_date.asc(),
        models.Observation.created_at.asc(),
        models.Observation.id.asc(),
    ).all()
    if not observations:
        return Response(
            "No observations have been recorded for this teacher in the selected academic year yet.",
            status_code=404,
            media_type="text/plain",
        )

    criteria = db.query(models.ObservationCriterion).filter(
        models.ObservationCriterion.is_active == True
    ).order_by(models.ObservationCriterion.sort_order.asc()).all()
    try:
        pdf_bytes = _build_teacher_cycle_pdf_report(
            request,
            db,
            teacher,
            observations,
            criteria,
        )
    except RuntimeError as exc:
        return Response(str(exc), status_code=503, media_type="text/plain")
    except Exception as exc:
        logger.exception("Teacher observation cycle PDF export failed teacher_id=%s", teacher.id)
        return Response(f"Teacher observation cycle PDF export failed: {exc}", status_code=500, media_type="text/plain")

    safe_teacher_name = "".join(
        ch for ch in _teacher_name(teacher).replace(" ", "_") if ch.isalnum() or ch in {"_", "-"}
    ) or f"teacher_{teacher.id}"
    filename = f"observation_progress_{safe_teacher_name}.pdf"
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/teacher/{teacher_id}/history")
def teacher_observation_history_page(teacher_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    prepare_observation_module(db)
    branch_id, academic_year_id = _get_scope_ids(current_user)
    teacher = db.query(models.Teacher).filter(
        models.Teacher.id == teacher_id,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).first()
    if not teacher:
        return RedirectResponse(url="/observations")
    if _is_teacher_user(current_user):
        current_teacher = _get_current_teacher(db, current_user)
        if not current_teacher or current_teacher.id != teacher.id:
            return RedirectResponse(url="/observations")

    observations = db.query(models.Observation).filter(
        models.Observation.teacher_id == teacher.id,
        models.Observation.branch_id == branch_id,
        models.Observation.academic_year_id == academic_year_id,
    ).order_by(
        models.Observation.observation_date.desc(),
        models.Observation.created_at.desc(),
        models.Observation.id.desc(),
    ).all()
    formal_observations = [
        observation
        for observation in reversed(observations)
        if _normalize_observation_type(observation.observation_type) == "Formal"
    ]
    formal_cycle_number = {
        observation.id: index
        for index, observation in enumerate(formal_observations, start=1)
    }
    evaluator_ids = {
        str(observation.evaluator_user_id or "").strip()
        for observation in observations
        if str(observation.evaluator_user_id or "").strip()
    }
    evaluators = {
        str(user.user_id): user
        for user in db.query(models.User).filter(models.User.user_id.in_(evaluator_ids)).all()
    } if evaluator_ids else {}

    rows = []
    for observation in observations:
        normalized_type = _normalize_observation_type(observation.observation_type)
        evaluator = evaluators.get(str(observation.evaluator_user_id or "").strip())
        export_state = _observation_export_state(db, observation)
        rows.append(
            {
                "observation": observation,
                "type": normalized_type,
                "cycle_number": formal_cycle_number.get(observation.id),
                "evaluator_name": _user_display_name(evaluator) if evaluator else str(observation.evaluator_user_id or "-"),
                "is_locked": _observation_is_locked(observation),
                "status_label": _observation_status_label(observation),
                "can_export": export_state["can_export"],
                "can_edit": _can_edit_observation(current_user, observation),
                "can_delete": _can_delete_observation(current_user, observation),
            }
        )

    cycle_state = _teacher_cycle_export_state(db, teacher.id, branch_id, academic_year_id)
    non_formal_count = sum(1 for row in rows if row["type"] == "Non-formal")
    locked_count = sum(1 for row in rows if row["is_locked"])
    return templates.TemplateResponse(
        request,
        "observation_history.html",
        {
            "request": request,
            **build_shell_context(
                request,
                db,
                current_user,
                page_key="observations",
                notice=request.query_params.get("notice", ""),
            ),
            "teacher": teacher,
            "teacher_name": _teacher_name(teacher),
            "rows": rows,
            "target": FORMAL_OBSERVATION_TARGET,
            "can_create": _can_create_observation(current_user),
            "can_export_cycle": cycle_state["can_export"],
            "summary": {
                "total": len(rows),
                "formal": len(formal_observations),
                "non_formal": non_formal_count,
                "locked": locked_count,
                "cycle_finalized": cycle_state["finalized_count"],
            },
        },
    )


@router.get("/{observation_id}/export/pdf")
def export_observation_pdf(observation_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    observation = _teacher_observation_access_filter(
        db.query(models.Observation).filter(models.Observation.id == observation_id),
        db,
        current_user,
    ).first()
    if not observation:
        return RedirectResponse(url="/observations")

    export_state = _observation_export_state(db, observation)
    if not export_state["can_export"]:
        return Response(
            "Observation PDF export is available only after the evaluator has signed, "
            "the teacher has completed the self-observation, the teacher has signed, "
            "and the observation is locked.",
            status_code=403,
            media_type="text/plain",
        )

    teacher = db.query(models.Teacher).filter(models.Teacher.id == observation.teacher_id).first()
    evaluator = db.query(models.User).filter(models.User.user_id == observation.evaluator_user_id).first()
    criteria = db.query(models.ObservationCriterion).filter(
        models.ObservationCriterion.is_active == True
    ).order_by(models.ObservationCriterion.sort_order.asc()).all()
    criteria_by_id = {criterion.id: criterion for criterion in criteria}
    score_rows = db.query(models.ObservationScore).filter(
        models.ObservationScore.observation_id == observation.id
    ).all()
    try:
        feedback = json.loads(observation.smart_feedback or "{}")
    except json.JSONDecodeError:
        feedback = _build_smart_feedback(score_rows, criteria_by_id)

    try:
        pdf_bytes = _build_observation_pdf_report(
            request,
            db,
            observation,
            teacher,
            evaluator,
            criteria,
            score_rows,
            export_state["self_evaluation"],
            export_state["self_scores_by_criterion"],
            feedback,
        )
    except RuntimeError as exc:
        return Response(str(exc), status_code=503, media_type="text/plain")
    except Exception as exc:
        logger.exception("Observation PDF export failed observation_id=%s", observation.id)
        return Response(f"Observation PDF export failed: {exc}", status_code=500, media_type="text/plain")

    safe_teacher_name = "".join(
        ch for ch in _teacher_name(teacher).replace(" ", "_") if ch.isalnum() or ch in {"_", "-"}
    ) or f"teacher_{observation.teacher_id}"
    filename = f"observation_{safe_teacher_name}_{observation.id}.pdf"
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{observation_id}")
def observation_detail_page(observation_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    observation = _teacher_observation_access_filter(
        db.query(models.Observation).filter(models.Observation.id == observation_id),
        db,
        current_user,
    ).first()
    if not observation:
        return RedirectResponse(url="/observations")

    teacher = db.query(models.Teacher).filter(models.Teacher.id == observation.teacher_id).first()
    criteria = db.query(models.ObservationCriterion).filter(
        models.ObservationCriterion.is_active == True
    ).order_by(models.ObservationCriterion.sort_order.asc()).all()
    criteria_by_id = {criterion.id: criterion for criterion in criteria}
    score_rows = db.query(models.ObservationScore).filter(
        models.ObservationScore.observation_id == observation.id
    ).all()
    scores_by_criterion = {score.criterion_id: score for score in score_rows}
    feedback = {}
    try:
        feedback = json.loads(observation.smart_feedback or "{}")
    except json.JSONDecodeError:
        feedback = _build_smart_feedback(score_rows, criteria_by_id)
    export_state = _observation_export_state(db, observation)
    self_evaluation = export_state["self_evaluation"]
    self_evaluation_scores_by_criterion = export_state["self_scores_by_criterion"]
    current_teacher = _get_current_teacher(db, current_user) if _is_teacher_user(current_user) else None
    self_evaluation_complete = export_state["self_evaluation_complete"]
    can_teacher_sign = bool(
        current_teacher
        and current_teacher.id == observation.teacher_id
        and observation.evaluator_signature_data
        and not observation.teacher_signature_data
        and not _observation_is_locked(observation)
        and self_evaluation_complete
    )
    can_self_evaluate = bool(
        current_teacher
        and current_teacher.id == observation.teacher_id
        and not _observation_is_locked(observation)
        and not self_evaluation_complete
    )
    can_update_evaluatee_notes = bool(
        current_teacher
        and current_teacher.id == observation.teacher_id
        and not _observation_is_locked(observation)
        and self_evaluation_complete
    )

    return templates.TemplateResponse(
        request,
        "observation_detail.html",
        {
            "request": request,
            **build_shell_context(
                request,
                db,
                current_user,
                page_key="observations",
                notice=request.query_params.get("notice", ""),
            ),
            "observation": observation,
            "teacher": teacher,
            "teacher_name": _teacher_name(teacher),
            "criteria_groups": _criteria_by_domain(criteria),
            "scores_by_criterion": scores_by_criterion,
            "feedback": feedback,
            "self_evaluation": self_evaluation,
            "self_evaluation_scores_by_criterion": self_evaluation_scores_by_criterion,
            "self_evaluation_complete": self_evaluation_complete,
            "is_locked": _observation_is_locked(observation),
            "status_label": _observation_status_label(observation),
            "can_edit_observation": _can_edit_observation(current_user, observation),
            "can_delete_observation": _can_delete_observation(current_user, observation),
            "can_export_observation": export_state["can_export"],
            "can_teacher_sign": can_teacher_sign,
            "can_self_evaluate": can_self_evaluate,
            "can_update_evaluatee_notes": can_update_evaluatee_notes,
        },
    )


@router.post("/{observation_id}/teacher-signature")
async def save_teacher_signature(observation_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")
    current_teacher = _get_current_teacher(db, current_user)
    observation = db.query(models.Observation).filter(models.Observation.id == observation_id).first()
    if not current_teacher or not observation or observation.teacher_id != current_teacher.id:
        return RedirectResponse(url="/observations")
    if _observation_is_locked(observation):
        return RedirectResponse(url=f"/observations/{observation.id}?notice=Observation+is+already+locked.", status_code=302)
    if not observation.evaluator_signature_data:
        return RedirectResponse(url=f"/observations/{observation.id}?notice=Evaluator+signature+is+required+before+teacher+signature.", status_code=302)
    self_evaluation = db.query(models.ObservationSelfEvaluation).filter(
        models.ObservationSelfEvaluation.observation_id == observation.id,
        models.ObservationSelfEvaluation.teacher_id == current_teacher.id,
    ).first()
    if not self_evaluation:
        return RedirectResponse(url=f"/observations/{observation.id}?notice=Complete+self-evaluation+before+signing.", status_code=302)
    has_self_rating = db.query(models.ObservationSelfEvaluationScore.id).filter(
        models.ObservationSelfEvaluationScore.self_evaluation_id == self_evaluation.id,
        models.ObservationSelfEvaluationScore.rating != "NA",
    ).first()
    if not has_self_rating:
        return RedirectResponse(url=f"/observations/{observation.id}?notice=Rate+at+least+one+self-evaluation+criterion+before+signing.", status_code=302)
    form = await request.form()
    signature_data = str(form.get("teacher_signature_data") or "").strip()
    if not signature_data:
        return RedirectResponse(url=f"/observations/{observation.id}?notice=Add+teacher+signature+first.", status_code=302)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    observation.teacher_signature_data = signature_data
    observation.status = "Locked"
    observation.locked_at = now
    observation.updated_at = now
    _notify_evaluator_teacher_signed(db, observation, current_teacher)
    db.commit()
    return RedirectResponse(url=f"/observations/{observation.id}?notice=Observation+signed+and+locked.", status_code=302)


@router.post("/{observation_id}/self-evaluation")
async def save_self_evaluation(observation_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")
    current_teacher = _get_current_teacher(db, current_user)
    observation = db.query(models.Observation).filter(models.Observation.id == observation_id).first()
    if not current_teacher or not observation or observation.teacher_id != current_teacher.id:
        return RedirectResponse(url="/observations")
    form = await request.form()
    self_evaluation = db.query(models.ObservationSelfEvaluation).filter(
        models.ObservationSelfEvaluation.observation_id == observation.id,
        models.ObservationSelfEvaluation.teacher_id == current_teacher.id,
    ).first()
    if not self_evaluation:
        self_evaluation = models.ObservationSelfEvaluation(
            observation_id=observation.id,
            teacher_id=current_teacher.id,
        )
        db.add(self_evaluation)
        db.flush()
    self_evaluation.reflection = str(form.get("evaluatee_notes") or "").strip()
    self_evaluation.strengths = ""
    self_evaluation.growth_areas = ""
    self_evaluation.support_needed = ""
    self_evaluation.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    observation.evaluatee_notes = self_evaluation.reflection
    observation.updated_at = self_evaluation.updated_at

    criteria = db.query(models.ObservationCriterion).filter(
        models.ObservationCriterion.is_active == True
    ).order_by(models.ObservationCriterion.sort_order.asc()).all()
    existing_scores = {
        score.criterion_id: score
        for score in db.query(models.ObservationSelfEvaluationScore).filter(
            models.ObservationSelfEvaluationScore.self_evaluation_id == self_evaluation.id
        ).all()
    }
    for criterion in criteria:
        raw_rating = str(form.get(f"self_rating_{criterion.id}") or "NA").strip().upper()
        rating = raw_rating if raw_rating == "NA" or raw_rating in RATING_VALUES else "NA"
        score = existing_scores.get(criterion.id)
        if not score:
            score = models.ObservationSelfEvaluationScore(
                self_evaluation_id=self_evaluation.id,
                criterion_id=criterion.id,
            )
            db.add(score)
        score.rating = rating
        score.evidence = str(form.get(f"self_evidence_{criterion.id}") or "").strip()
    _notify_evaluator_self_evaluation_saved(db, observation, current_teacher)
    db.commit()
    return RedirectResponse(url=f"/observations/{observation.id}?notice=Self-evaluation+saved", status_code=302)


@router.post("/{observation_id}/evaluatee-notes")
async def save_evaluatee_notes(observation_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    observation = _teacher_observation_access_filter(
        db.query(models.Observation).filter(models.Observation.id == observation_id),
        db,
        current_user,
    ).first()
    if not observation:
        return RedirectResponse(url="/observations")
    if observation.locked_at or observation.status == "Locked":
        return RedirectResponse(
            url=f"/observations/{observation.id}?notice=Observation+is+locked+after+signatures.",
            status_code=302,
        )

    form = await request.form()
    observation.evaluatee_notes = str(form.get("evaluatee_notes") or "").strip()
    observation.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return RedirectResponse(url=f"/observations/{observation.id}?notice=Notes+saved", status_code=302)


def _parse_int(value):
    try:
        return int(str(value or "").strip())
    except ValueError:
        return None
