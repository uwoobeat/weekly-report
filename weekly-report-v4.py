import os
import sys
import re
import json
import subprocess
from datetime import datetime, timedelta
import git
from pathlib import Path
from collections import defaultdict

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


def get_all_prs_for_repo(repo_full_name, since_date):
    """레포지토리의 모든 PR을 가져와서 브랜치명으로 인덱싱"""
    cmd = ["gh", "pr", "list", "--state", "all",
           "--search", f"updated:>={since_date}",
           "--json", "number,title,state,updatedAt,url,mergedAt,baseRefName,headRefName,author",
           "--repo", repo_full_name, "--limit", "100"]

    all_prs = run_gh_command(cmd)
    pr_by_branch = {}

    for pr in all_prs:
        # develop -> main으로 가는 PR이면서 v1.2.3 형식의 제목을 가진 PR 필터링
        if (pr.get('baseRefName') == 'main' and
                pr.get('headRefName') == 'develop' and
                re.match(r'^v\d+\.\d+\.\d+', pr.get('title', ''))):
            continue

        # 헤드 브랜치명으로 인덱싱
        head_branch = pr.get('headRefName')
        if head_branch:
            pr_by_branch[head_branch] = pr

    return pr_by_branch


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

        # 브랜치의 고유 커밋만 가져오기 (develop에 없는 커밋만)
        # `--not origin/develop` 옵션을 사용하여 develop 브랜치에 있는 커밋 제외
        log_output = git_repo.git.log(
            f'origin/{branch_name}',
            '--not', 'origin/develop',
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


def format_timestamp(timestamp):
    """ISO 타임스탬프를 읽기 쉬운 형식으로 변환"""
    if not timestamp:
        return ""

    # 날짜와 시간 포맷 변경 (2023-04-14T15:30:45Z -> 2023-04-14 15:30)
    timestamp_full = timestamp
    updated_parts = timestamp_full.replace('Z', '').split('T')
    if len(updated_parts) >= 2:
        date_part = updated_parts[0]
        time_part = updated_parts[1][:5]  # HH:MM 부분만 추출
        return f"{date_part} {time_part}"
    else:
        return timestamp_full


def generate_summary_section(repo_full_name, user_data, all_prs, days_ago_str, today_str):
    """요약 섹션 생성"""
    summary = f"## 📈 주간 요약\n\n"

    # 전체 통계 계산
    total_prs = len(all_prs)
    pr_open = sum(1 for pr in all_prs.values() if pr['state'] == 'OPEN')
    pr_merged = sum(1 for pr in all_prs.values() if pr['mergedAt'])
    pr_closed = sum(1 for pr in all_prs.values() if pr['state'] == 'CLOSED' and not pr['mergedAt'])

    total_wip_branches = sum(len(user_data[username]['wip_branches']) for username in user_data)
    total_wip_commits = sum(user_data[username]['wip_commit_count'] for username in user_data)

    # 전체 통계 요약
    summary += f"### 📊 전체 통계\n\n"
    summary += f"- **검토 기간**: {days_ago_str} ~ {today_str}\n"
    summary += f"- **PR 현황**: 총 {total_prs}개 (진행 중: {pr_open}개, 머지됨: {pr_merged}개, 닫힘: {pr_closed}개)\n"
    summary += f"- **작업 중인 브랜치**: {total_wip_branches}개 (커밋: {total_wip_commits}개)\n\n"

    # 사용자별 요약
    summary += f"### 👥 사용자별 활동\n\n"
    summary += "| 사용자 | PR 수 | 머지된 PR | 진행 중 PR | 작업 중인 브랜치 |\n"
    summary += "| ------ | ----- | --------- | ---------- | ---------------- |\n"

    for username in user_data:
        user_prs = len(user_data[username]['prs'])
        user_merged_prs = sum(1 for pr in user_data[username]['prs'] if pr['mergedAt'])
        user_open_prs = sum(1 for pr in user_data[username]['prs'] if pr['state'] == 'OPEN')
        user_wip_branches = len(user_data[username]['wip_branches'])

        summary += f"| @{username} | {user_prs} | {user_merged_prs} | {user_open_prs} | {user_wip_branches} |\n"

    summary += "\n"

    # 주요 활동 하이라이트
    summary += f"### 🔥 주요 활동 하이라이트\n\n"

    # 최근 머지된 PR 목록
    summary += f"#### ✅ 최근 머지된 PR\n\n"
    merged_prs = []
    for pr in all_prs.values():
        if pr['mergedAt']:
            merged_prs.append({
                'username': pr['author']['login'],
                'number': pr['number'],
                'title': pr['title'],
                'url': pr['url'],
                'mergedAt': pr['mergedAt']
            })

    if merged_prs:
        merged_prs.sort(key=lambda x: x['mergedAt'], reverse=True)  # 최근 머지된 순으로 정렬
        summary += "| PR | 작성자 | 제목 | 머지일 |\n"
        summary += "| -- | ------ | ---- | ------ |\n"

        # 최대 5개만 표시
        for i, pr in enumerate(merged_prs[:5]):
            merge_date = format_timestamp(pr['mergedAt'])
            summary += f"| [#{pr['number']}](<{pr['url']}>) | @{pr['username']} | {pr['title']} | {merge_date} |\n"

        if len(merged_prs) > 5:
            summary += f"\n*... 외 {len(merged_prs) - 5}개 더 있습니다.*\n"
    else:
        summary += "해당 기간 동안 머지된 PR이 없습니다.\n"

    summary += "\n"

    # 활발한 PR 목록 (최근 업데이트된 오픈 PR)
    summary += f"#### 🔄 활발한 PR\n\n"
    active_prs = []
    for pr in all_prs.values():
        if pr['state'] == 'OPEN':
            active_prs.append({
                'username': pr['author']['login'],
                'number': pr['number'],
                'title': pr['title'],
                'url': pr['url'],
                'updatedAt': pr['updatedAt']
            })

    if active_prs:
        active_prs.sort(key=lambda x: x['updatedAt'], reverse=True)  # 최근 업데이트 순으로 정렬
        summary += "| PR | 작성자 | 제목 | 마지막 업데이트 |\n"
        summary += "| -- | ------ | ---- | -------------- |\n"

        # 최대 5개만 표시
        for i, pr in enumerate(active_prs[:5]):
            update_date = format_timestamp(pr['updatedAt'])
            summary += f"| [#{pr['number']}](<{pr['url']}>) | @{pr['username']} | {pr['title']} | {update_date} |\n"

        if len(active_prs) > 5:
            summary += f"\n*... 외 {len(active_prs) - 5}개 더 있습니다.*\n"
    else:
        summary += "해당 기간 동안 활발한 PR이 없습니다.\n"

    summary += "\n"

    return summary


def generate_markdown_report(repo_full_name, user_handles, git_repo, days):
    """사용자 활동 마크다운 레포트 생성"""
    # 지난 일주일 날짜 범위 계산
    today = datetime.now()
    days_ago = today - timedelta(days=days)
    days_ago_str = days_ago.strftime('%Y-%m-%d')
    today_str = today.strftime('%Y-%m-%d')

    # 모든 PR 가져오기
    all_prs_by_branch = get_all_prs_for_repo(repo_full_name, days_ago_str)
    print(f"레포지토리 전체 PR 수: {len(all_prs_by_branch)}")

    # 사용자별 데이터를 저장할 딕셔너리
    user_data = {username: {
        'prs': [],  # 사용자가 작성하거나 할당된 PR
        'wip_branches': [],  # PR이 없는 작업 중인 브랜치
        'wip_commit_count': 0,  # PR 없는 브랜치의 총 커밋 수
        'issues': []  # 할당된 이슈
    } for username in user_handles}

    # 레포트 헤더 시작
    markdown = f"# 📊 주간 작업 레포트\n\n"
    markdown += f"*기간: {days_ago_str} ~ {today_str}*\n\n"
    markdown += f"*레포지토리: {repo_full_name}*\n\n"

    # 각 사용자별 PR 정보 수집
    for username in user_handles:
        print(f"사용자 처리 중: {username}")

        # 1. 사용자가 작성한 PR 가져오기
        cmd = ["gh", "pr", "list", "--author", username, "--state", "all",
               "--search", f"updated:>={days_ago_str}",
               "--json", "number,title,state,updatedAt,url,mergedAt,baseRefName,headRefName",
               "--repo", repo_full_name]
        authored_prs = run_gh_command(cmd)

        # 2. 사용자에게 할당된 PR 가져오기
        cmd = ["gh", "pr", "list", "--assignee", username, "--state", "all",
               "--search", f"updated:>={days_ago_str}",
               "--json", "number,title,state,updatedAt,url,mergedAt,baseRefName,headRefName",
               "--repo", repo_full_name]
        assigned_prs = run_gh_command(cmd)

        # PR 병합 (중복 제거)
        unique_prs = {}
        for pr_list in [authored_prs, assigned_prs]:
            for pr in pr_list:
                # 버전 릴리스 PR 필터링
                if (pr.get('baseRefName') == 'main' and
                        pr.get('headRefName') == 'develop' and
                        re.match(r'^v\d+\.\d+\.\d+', pr.get('title', ''))):
                    continue

                unique_prs[pr['number']] = pr

        # 사용자 데이터에 PR 추가
        user_data[username]['prs'] = list(unique_prs.values())
        print(f"{username}의 PR {len(user_data[username]['prs'])}개 발견됨")

        # 3. 사용자에게 할당된 오픈 이슈 가져오기
        cmd = ["gh", "issue", "list", "--assignee", username, "--state", "open",
               "--json", "number,title,url", "--repo", repo_full_name]
        assigned_issues = run_gh_command(cmd)
        user_data[username]['issues'] = assigned_issues
        print(f"{username}의 오픈 이슈 {len(assigned_issues)}개 발견됨")

        # 4. PR 없는 작업 중인 브랜치 찾기
        for issue in assigned_issues:
            issue_number = issue['number']
            branches = find_branches_for_issue(git_repo, issue_number)

            for branch in branches:
                # PR이 없는 브랜치만 처리
                if branch not in all_prs_by_branch:
                    commits = get_commits_for_branch(git_repo, branch, username, days_ago_str)

                    if commits:
                        user_data[username]['wip_branches'].append({
                            'name': branch,
                            'issue': issue,
                            'commits': commits
                        })
                        user_data[username]['wip_commit_count'] += len(commits)

    # 사용자별 상세 정보 섹션 생성
    for username in user_handles:
        user_section = f"## @{username}\n\n"

        # 1. PR 활동 섹션
        user_section += f"### 🔄 PR 활동\n\n"

        if user_data[username]['prs']:
            # PR을 상태별로 분류
            open_prs = [pr for pr in user_data[username]['prs'] if pr['state'] == 'OPEN']
            merged_prs = [pr for pr in user_data[username]['prs'] if pr['mergedAt']]
            closed_prs = [pr for pr in user_data[username]['prs'] if pr['state'] == 'CLOSED' and not pr['mergedAt']]

            # 진행 중인 PR
            if open_prs:
                user_section += f"#### 진행 중인 PR ({len(open_prs)}개)\n\n"
                user_section += "| PR | 제목 | 대상 브랜치 | 마지막 업데이트 |\n"
                user_section += "| -- | ---- | ----------- | -------------- |\n"

                for pr in sorted(open_prs, key=lambda x: x['updatedAt'], reverse=True):
                    pr_number = pr['number']
                    pr_title = pr['title']
                    pr_base = pr['baseRefName']
                    pr_updated = format_timestamp(pr['updatedAt'])
                    pr_url = pr['url']

                    user_section += f"| [#{pr_number}](<{pr_url}>) | {pr_title} | `{pr_base}` | {pr_updated} |\n"

                user_section += "\n"

            # 머지된 PR
            if merged_prs:
                user_section += f"#### 머지된 PR ({len(merged_prs)}개)\n\n"
                user_section += "| PR | 제목 | 대상 브랜치 | 머지일 |\n"
                user_section += "| -- | ---- | ----------- | ------ |\n"

                for pr in sorted(merged_prs, key=lambda x: x['mergedAt'], reverse=True):
                    pr_number = pr['number']
                    pr_title = pr['title']
                    pr_base = pr['baseRefName']
                    pr_merged = format_timestamp(pr['mergedAt'])
                    pr_url = pr['url']

                    user_section += f"| [#{pr_number}](<{pr_url}>) | {pr_title} | `{pr_base}` | {pr_merged} |\n"

                user_section += "\n"

            # 닫힌 PR (머지되지 않음)
            if closed_prs:
                user_section += f"#### 닫힌 PR ({len(closed_prs)}개)\n\n"
                user_section += "| PR | 제목 | 대상 브랜치 | 마지막 업데이트 |\n"
                user_section += "| -- | ---- | ----------- | -------------- |\n"

                for pr in sorted(closed_prs, key=lambda x: x['updatedAt'], reverse=True):
                    pr_number = pr['number']
                    pr_title = pr['title']
                    pr_base = pr['baseRefName']
                    pr_updated = format_timestamp(pr['updatedAt'])
                    pr_url = pr['url']

                    user_section += f"| [#{pr_number}](<{pr_url}>) | {pr_title} | `{pr_base}` | {pr_updated} |\n"

                user_section += "\n"
        else:
            user_section += f"해당 기간 동안 {username}의 PR 활동이 없습니다.\n\n"

        # 2. 작업 중인 브랜치 (PR 없음) 섹션
        user_section += f"### 🌿 작업 중인 브랜치 (PR 없음)\n\n"

        if user_data[username]['wip_branches']:
            for branch_info in user_data[username]['wip_branches']:
                branch_name = branch_info['name']
                issue = branch_info['issue']
                commits = branch_info['commits']

                user_section += f"#### 브랜치: `{branch_name}`\n\n"
                user_section += f"- **관련 이슈**: [#{issue['number']}](<{issue['url']}>) - {issue['title']}\n"
                user_section += f"- **커밋 수**: {len(commits)}개\n\n"

                user_section += "| 날짜 및 시간 | 커밋 | 메시지 |\n"
                user_section += "| ----------- | ---- | ------ |\n"

                for commit in sorted(commits, key=lambda x: x['date'], reverse=True):
                    commit_url = f"https://github.com/{repo_full_name}/commit/{commit['hash']}"
                    user_section += f"| {commit['date']} | [{commit['hash'][:7]}](<{commit_url}>) | {commit['message']} |\n"

                user_section += "\n"
        else:
            user_section += f"해당 기간 동안 {username}의 PR이 없는 작업 중인 브랜치가 없습니다.\n\n"

        # 사용자 섹션 추가
        markdown += user_section

    # 요약 섹션 생성 및 마크다운 상단에 추가
    summary_section = generate_summary_section(repo_full_name, user_data, all_prs_by_branch, days_ago_str, today_str)
    markdown = markdown.split("\n\n", 3)  # 헤더 부분을 분리
    markdown = "\n\n".join(markdown[:3]) + "\n\n" + summary_section + "\n\n" + markdown[3]

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