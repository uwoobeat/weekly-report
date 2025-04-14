import os
import sys
import re
import json
import subprocess
from datetime import datetime, timedelta
import git
from pathlib import Path

# ============= 설정값 (여기서 수정하세요) =============
# 레포지토리 이름 (형식: 소유자/레포지토리명)
REPO_NAME = "gdg-hongik-univ/gdsc-server"

# 검토할 사용자 핸들 (쉼표로 구분)
USERS = ["uwoobeat", "Sangwook02", "kckc0608", "kimsh1017"]  # 실제 사용자명으로 변경하세요

# 검토 기간 (일)
DAYS = 7

# 현재 위치는 '/Users/uwoobeat/repo/weekly-report', 레포 위치는 '/Users/uwoobeat/repo/gdsc-server'
GIT_PATH = Path.cwd().parent / "gdsc-server"  # 레포지토리 경로로 변경하세요

# 출력 파일 경로
OUTPUT_PATH = Path.cwd() / "report.md"


# ====================================================

def check_gh_cli():
    """GitHub CLI 설치 및 인증 상태 확인"""
    try:
        # GitHub CLI 버전 확인으로 설치 여부 확인
        result = subprocess.run(["gh", "--version"], capture_output=True, text=True)
        print(f"GitHub CLI 설치됨: {result.stdout.splitlines()[0]}")

        # 인증 상태 확인
        result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        if "Logged in to" in result.stdout:
            print(f"GitHub CLI 인증됨: {result.stdout.splitlines()[0]}")
            return True
        else:
            print("GitHub CLI 인증이 필요합니다. 'gh auth login' 명령어를 실행하세요.")
            return False
    except subprocess.CalledProcessError:
        print("GitHub CLI 명령어 실행 중 오류가 발생했습니다.")
        return False
    except FileNotFoundError:
        print("GitHub CLI가 설치되어 있지 않습니다. https://cli.github.com에서 설치하세요.")
        return False


def run_gh_command(command):
    """GitHub CLI 명령어를 실행하고 JSON 결과를 반환"""
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        if not result.stdout.strip():
            return []
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"GitHub CLI 명령어 실행 오류: {e}")
        print(f"명령어: {' '.join(command)}")
        print(f"에러 메시지: {e.stderr}")
        return []
    except json.JSONDecodeError as e:
        print(f"GitHub CLI 응답 JSON 파싱 오류: {e}")
        print(f"명령어: {' '.join(command)}")
        print(f"출력: {result.stdout}")
        return []


def find_branches_for_issue(git_repo, issue_number):
    """특정 이슈 번호에 관련된 브랜치 찾기 (네이밍 컨벤션 사용)"""
    branches = []

    # git을 통해 원격 브랜치 목록 가져오기
    try:
        # 모든 원격 브랜치 새로고침
        git_repo.git.fetch('--all')

        # 모든 원격 브랜치 가져오기
        for ref in git_repo.remote().refs:
            branch_name = ref.name.replace('origin/', '')

            # 브랜치 네이밍 컨벤션 매치: {type}/{issue-number}-{description}
            pattern = r'[\w-]+/' + str(issue_number) + r'-[\w-]+'
            if re.match(pattern, branch_name):
                branches.append(branch_name)
    except Exception as e:
        print(f"브랜치 검색 오류: {str(e)}")

    return branches


def get_commits_for_branch(git_repo, branch_name, username, since_date):
    """특정 브랜치에서 특정 사용자의 특정 날짜 이후 커밋 가져오기"""
    commits = []
    try:
        # 원격 브랜치 가져오기 시도
        try:
            git_repo.git.fetch('origin', branch_name)
        except Exception as e:
            print(f"브랜치 {branch_name} fetch 오류: {str(e)}")
            print("이미 존재하는 참조를 사용하여 계속 진행합니다.")

        # git log 명령 형식 - 날짜/시간 포함
        format_str = "%H|%s|%ad|%an"

        # develop 브랜치와 비교하여 커밋 가져오기
        # 1. develop 브랜치를 먼저 가져오기
        try:
            git_repo.git.fetch('origin', 'develop')
        except Exception as e:
            print(f"develop 브랜치 fetch 오류: {str(e)}")

        # 2. 브랜치의 커밋 가져오기 - 이제 날짜 포맷을 상세하게 변경 (날짜 및 시간 포함)
        log_output = git_repo.git.log(
            f'origin/{branch_name}',
            f'--since={since_date}',
            f'--author={username}',
            f'--pretty=format:{format_str}',
            f'--date=iso'  # ISO 형식으로 날짜 및 시간 표시
        )

        # 커밋 데이터 파싱
        if log_output:
            for line in log_output.split('\n'):
                if line.strip():
                    parts = line.split('|')
                    if len(parts) >= 4:
                        commit_hash = parts[0]
                        commit_message = parts[1]
                        commit_date = parts[2]

                        # 날짜/시간 형식 포맷팅 (2023-04-14 15:30:45 +0900 형식에서 추출)
                        datetime_parts = commit_date.split(' ')
                        if len(datetime_parts) >= 2:
                            date_part = datetime_parts[0]
                            time_part = datetime_parts[1]
                            formatted_datetime = f"{date_part} {time_part}"
                        else:
                            formatted_datetime = commit_date

                        commits.append({
                            'hash': commit_hash,
                            'message': commit_message,
                            'date': formatted_datetime
                        })
    except Exception as e:
        print(f"브랜치 {branch_name}의 커밋 조회 오류: {str(e)}")

    return commits


def generate_markdown_report(repo_full_name, user_handles, git_repo, days):
    """사용자 활동 마크다운 레포트 생성"""
    # 지난 일주일 날짜 범위 계산
    today = datetime.now()
    days_ago = today - timedelta(days=days)
    days_ago_str = days_ago.strftime('%Y-%m-%d')
    today_str = today.strftime('%Y-%m-%d')

    markdown = f"# 📊 주간 작업 레포트\n\n"
    markdown += f"*기간: {days_ago_str} ~ {today_str}*\n\n"
    markdown += f"*레포지토리: {repo_full_name}*\n\n"

    for username in user_handles:
        print(f"사용자 처리 중: {username}")
        markdown += f"## @{username}\n\n"

        # GitHub CLI로 사용자에게 할당된 오픈 이슈 가져오기
        cmd = ["gh", "issue", "list", "--assignee", username, "--state", "open",
               "--json", "number,title,url", "--repo", repo_full_name]
        assigned_issues = run_gh_command(cmd)
        print(f"{username}의 오픈 이슈 {len(assigned_issues)}개 발견됨")

        # 활성 브랜치 커밋
        markdown += f"### 🌿 활성 브랜치 커밋 내역\n\n"

        if not assigned_issues:
            markdown += f"{username}에게 할당된 오픈 이슈가 없습니다.\n\n"
        else:
            active_issues_found = False

            for issue in assigned_issues:
                issue_number = issue['number']
                issue_title = issue['title']
                issue_url = issue['url']

                branches = find_branches_for_issue(git_repo, issue_number)
                active_branches_found = False

                if branches:
                    issue_added = False

                    for branch in branches:
                        commits = get_commits_for_branch(git_repo, branch, username, days_ago_str)

                        # 커밋이 있는 브랜치만 표시
                        if commits:
                            # 이슈 정보는 최초 활성 브랜치 발견 시에만 한 번 추가
                            if not issue_added:
                                markdown += f"#### 이슈 [#{issue_number}](<{issue_url}>) - {issue_title}\n\n"
                                issue_added = True
                                active_issues_found = True

                            markdown += f"##### 브랜치: `{branch}`\n\n"
                            active_branches_found = True

                            markdown += "| 날짜 및 시간 | 커밋 | 메시지 |\n"
                            markdown += "| ----------- | ---- | ------ |\n"

                            for commit in commits:
                                commit_url = f"https://github.com/{repo_full_name}/commit/{commit['hash']}"
                                markdown += f"| {commit['date']} | [{commit['hash'][:7]}](<{commit_url}>) | {commit['message']} |\n"

                            markdown += "\n"

            if not active_issues_found:
                markdown += f"지난 {days}일 동안 활성화된 브랜치에 커밋이 없습니다.\n\n"

        # PR 활동
        markdown += f"### 🔄 PR 활동 내역\n\n"

        # GitHub CLI를 사용하여 사용자의 PR 가져오기 - 업데이트 시간 포맷 변경
        cmd = ["gh", "pr", "list", "--assignee", username, "--state", "all",
               "--search", f"updated:>={days_ago_str}",
               "--json", "number,title,state,updatedAt,url,mergedAt,baseRefName,headRefName",
               "--repo", repo_full_name]
        user_prs = run_gh_command(cmd)

        print(f"지난 {days}일 동안 {username}의 PR {len(user_prs)}개 발견됨")

        # v1.2.3 형식의 버전 릴리스 PR 필터링 (develop -> main 타겟)
        filtered_prs = []
        for pr in user_prs:
            # develop -> main으로 가는 PR이면서 v1.2.3 형식의 제목을 가진 PR 필터링
            if (pr.get('baseRefName') == 'main' and
                    pr.get('headRefName') == 'develop' and
                    re.match(r'^v\d+\.\d+\.\d+', pr.get('title', ''))):
                print(f"버전 릴리스 PR 제외: {pr.get('title')}")
                continue
            filtered_prs.append(pr)

        print(f"버전 릴리스 PR 제외 후 {len(filtered_prs)}개 PR 남음")

        if not filtered_prs:
            markdown += f"지난 {days}일 동안 {username}의 PR이 없습니다.\n\n"
        else:
            markdown += "| 상태 | PR | 마지막 업데이트 |\n"
            markdown += "| ---- | -- | -------------- |\n"

            for pr in filtered_prs:
                pr_number = pr['number']
                pr_title = pr['title']
                pr_state = pr['state']

                # 날짜와 시간 포맷 변경 (2023-04-14T15:30:45Z -> 2023-04-14 15:30)
                pr_updated_full = pr['updatedAt']
                updated_parts = pr_updated_full.replace('Z', '').split('T')
                if len(updated_parts) >= 2:
                    pr_date = updated_parts[0]
                    pr_time = updated_parts[1][:5]  # HH:MM 부분만 추출
                    pr_updated = f"{pr_date} {pr_time}"
                else:
                    pr_updated = pr_updated_full

                pr_url = pr['url']
                merged_at = pr['mergedAt']

                if pr_state == "OPEN":
                    status = "🔄 진행 중"
                elif merged_at:
                    status = "✅ 머지됨"
                else:
                    status = "❌ 닫힘"

                markdown += f"| {status} | [#{pr_number}](<{pr_url}>) {pr_title} | {pr_updated} |\n"

            markdown += "\n"

        markdown += "\n"

    return markdown


def main():
    """메인 함수"""
    # GitHub Actions 환경에서 실행 중인지 확인
    in_github_actions = os.environ.get('GITHUB_ACTIONS') == 'true'

    # GitHub Actions에서는 환경 변수 사용, 로컬에서는 하드코딩된 값 사용
    if in_github_actions:
        repo_full_name = os.environ.get('GITHUB_REPOSITORY')
        user_handles = [user.strip() for user in os.environ.get('USER_HANDLES', '').split(',') if user.strip()]
        days = 7
        output_path = Path('report.md')
    else:
        # 하드코딩된 값 사용
        repo_full_name = REPO_NAME
        user_handles = USERS
        days = DAYS
        output_path = OUTPUT_PATH

    # GitHub CLI 확인 (GitHub Actions에서는 건너뜀)
    if not in_github_actions:
        if not check_gh_cli():
            print("GitHub CLI 설정이 필요합니다.")
            print("'gh auth login' 명령어로 GitHub에 로그인하세요.")
            sys.exit(1)

    # Git 저장소 초기화
    try:
        git_repo = git.Repo(GIT_PATH)
        print(f"Git 저장소 초기화 완료: {GIT_PATH}")
    except Exception as e:
        print(f"Git 저장소 초기화 오류: {str(e)}")
        sys.exit(1)

    # 실행 정보 출력
    print(f"레포지토리: {repo_full_name}")
    print(f"사용자: {', '.join(user_handles)}")
    print(f"검토 기간: {days}일")
    print(f"출력 파일: {output_path}")
    print("-" * 50)

    # 레포트 생성 및 저장
    try:
        report = generate_markdown_report(repo_full_name, user_handles, git_repo, days)

        # 출력 디렉토리가 없으면 생성
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"레포트 생성 완료! 저장 위치: {output_path}")

        # 결과 미리보기
        print("\n레포트 미리보기:")
        print("-" * 50)
        preview_lines = report.split('\n')[:20]  # 처음 20줄만 출력
        print('\n'.join(preview_lines))
        print("...")
        print(f"전체 레포트는 {output_path}에서 확인하세요.")

    except Exception as e:
        print(f"레포트 생성 오류: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\n처리 완료!")


if __name__ == "__main__":
    main()
