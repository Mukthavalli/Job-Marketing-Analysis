from flask import Flask, jsonify, send_from_directory, request
import pandas as pd
import os
import pycountry
import requests as req_lib
import re
import time
from datetime import datetime
import math

app = Flask(__name__, static_folder='static')
CSV_FILE = 'ds_salaries.csv'

# ═══════════════════════════════════════════════════════════════════
#  DATA LAYER — CSV is loaded & processed ONCE at startup
#  All request handlers call get_data() which returns a copy of
#  the cached DataFrame in ~0ms instead of re-reading the file.
# ═══════════════════════════════════════════════════════════════════
_cached_df = None
_default_df = None

def _get_country_name(code):
    try:
        return pycountry.countries.get(alpha_2=code).name
    except Exception:
        return code

def _build_dataframe(custom_df=None):
    global _cached_df, _default_df
    
    if custom_df is not None:
        df = custom_df.copy()
    else:
        try:
            df = pd.read_csv(CSV_FILE)
        except Exception as e:
            print(f"[ERROR] Could not read {CSV_FILE}: {e}")
            df = pd.DataFrame()

    if df.empty:
        _cached_df = df
        return

    # Mappings
    exp_map = {'EN': 'Entry Level', 'MI': 'Mid Level', 'SE': 'Senior Level', 'EX': 'Executive Level'}
    size_map = {'S': 'Startup / Small Enterprise', 'M': 'Mid-Size / Product Based', 'L': 'Large Enterprise / MNC'}
    emp_map = {'PT': 'Part-Time', 'FT': 'Full-Time', 'CT': 'Contract', 'FL': 'Freelance'}
    remote_map = {0: 'On-site', 50: 'Hybrid', 100: 'Remote'}

    if 'experience_level' in df.columns:
        df['experience_level'] = df['experience_level'].map(exp_map).fillna(df['experience_level'])
    if 'company_size' in df.columns:
        df['company_size'] = df['company_size'].map(size_map).fillna(df['company_size'])
    if 'employment_type' in df.columns:
        df['employment_type'] = df['employment_type'].map(emp_map).fillna(df['employment_type'])

    # Normalization (handles both standard dataset and mapped custom dataset)
    if 'company_location' in df.columns and 'company_location_full' not in df.columns:
        country_cache = {code: _get_country_name(code) for code in df['company_location'].unique() if pd.notnull(code)}
        df['company_location_full'] = df['company_location'].map(country_cache).fillna('Unknown')
    elif 'company_location_full' not in df.columns:
        df['company_location_full'] = 'Unknown'

    if 'remote_ratio' in df.columns and 'remote_status' not in df.columns:
        # Check if the column is numerical (0, 50, 100)
        df['remote_status'] = pd.to_numeric(df['remote_ratio'], errors='coerce').map(remote_map)
        # For strings, apply the old logic or fillna
        df['remote_status'] = df['remote_status'].fillna(df['remote_ratio']).replace({100: 'Remote', 0: 'On-site', 50: 'Hybrid', '100': 'Remote', '0': 'On-site', '50': 'Hybrid'})
    elif 'remote_status' not in df.columns:
        df['remote_status'] = 'Unknown'

    # Clean missing values
    for col in ['work_year', 'salary_in_usd']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

    for col in ['job_title', 'experience_level', 'company_size', 'employment_type']:
        if col in df.columns:
            df[col] = df[col].fillna('Unknown').astype(str)

    _cached_df = df
    if custom_df is None and _default_df is None:
        _default_df = df.copy()
        print(f"[OK] Pre-loaded {len(df):,} rows into memory cache")
    elif custom_df is not None:
        print(f"[OK] Custom dataset loaded with {len(df):,} rows")

    return df

def get_data():
    global _cached_df
    if _cached_df is not None:
        return _cached_df.copy()
    _build_dataframe()
    return _cached_df.copy()


def apply_global_filters(df, args):
    if df.empty:
        return df
    exp = args.get('experience')
    if exp and exp != 'All':
        df = df[df['experience_level'] == exp]
    size = args.get('company_size')
    if size and size != 'All':
        df = df[df['company_size'] == size]
    return df


# Pre-warm cache at import time so the very first request is instant
try:
    _cached_df = _build_dataframe()
    print(f"[OK] Pre-loaded {len(_cached_df):,} rows into memory cache")
except Exception as _e:
    print(f"[ERROR] Pre-load failed: {_e}")

# ═══════════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


@app.route('/api/upload_dataset', methods=['POST'])
def upload_dataset():
    import json
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'})
    
    mapping_str = request.form.get('mapping', '{}')
    try:
        mapping = json.loads(mapping_str)
    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid column mapping'})

    try:
        # Read the custom CSV
        df = pd.read_csv(file)
        
        # If mapping is provided, rename columns
        # mapping is { "target_column": "source_csv_column" }
        # expected targets: job_title, salary_in_usd, experience_level, etc.
        rename_dict = { v: k for k, v in mapping.items() if v in df.columns }
        if rename_dict:
            df = df.rename(columns=rename_dict)
            
        if 'salary_in_usd' not in df.columns or 'job_title' not in df.columns:
            return jsonify({'error': 'DATA_MISSING_CORE: Your dataset MUST contain a mapped Salary column and Job Title column. The dashboard relies heavily on salary data to function.'})
        
        # Build dataset cache using this new DF
        _build_dataframe(custom_df=df)
        return jsonify({'status': 'ok', 'message': f'Dataset updated with {len(df)} rows.', 'rows': len(df)})
    except Exception as e:
        print(f"Upload error: {e}")
        return jsonify({'error': str(e)})

@app.route('/api/reset_dataset', methods=['POST'])
def reset_dataset():
    global _cached_df, _default_df
    if _default_df is not None:
        _cached_df = _default_df.copy()
        return jsonify({'status': 'ok', 'message': 'Dataset reset to default.'})
    return jsonify({'error': 'Default dataset not found.'})

@app.route('/api/filters')
def get_filters():
    df = get_data()
    
    is_custom = False
    if _default_df is not None and len(_cached_df) != len(_default_df):
        is_custom = True
    elif _default_df is not None:
        try:
            is_custom = not _cached_df.equals(_default_df)
        except Exception:
            is_custom = True
            
    if df.empty:
        return jsonify({})
    return jsonify({
        'is_custom': is_custom,
        'experience_levels': sorted(df['experience_level'].dropna().unique().tolist()),
        'company_sizes':     sorted(df['company_size'].dropna().unique().tolist()),
        'years':             sorted(df['work_year'].dropna().unique().tolist()),
        'countries':         sorted(df['company_location_full'].dropna().unique().tolist()),
        'job_titles':        sorted(df['job_title'].dropna().unique().tolist()),
    })


@app.route('/api/dashboard')
def dashboard_stats():
    df = get_data()
    df = apply_global_filters(df, request.args)
    
    if df.empty:
        return jsonify({'error': 'No data available for the current selection.'})

    summary = {
        'total_jobs':   len(df),
        'avg_salary':   int(df['salary_in_usd'].mean()) if 'salary_in_usd' in df.columns else 0,
        'max_salary':   int(df['salary_in_usd'].max()) if 'salary_in_usd' in df.columns else 0,
        'unique_roles': int(df['job_title'].nunique()) if 'job_title' in df.columns else 0,
    }

    # Top 7 roles by salary (filtered by volume)
    role_stats = df.groupby('job_title')['salary_in_usd'].agg(['mean', 'count']).reset_index()
    top_roles  = role_stats.sort_values('count', ascending=False).head(7)
    roles_chart = {
        'labels':   top_roles['job_title'].tolist(),
        'salaries': [int(x) for x in top_roles['mean'].tolist()],
    }

    # Experience vs Salary
    sort_order = ['Entry Level', 'Mid Level', 'Senior Level', 'Executive Level']
    exp_stats  = df.groupby('experience_level')['salary_in_usd'].mean().reset_index()
    exp_stats['experience_level'] = pd.Categorical(
        exp_stats['experience_level'], categories=sort_order, ordered=True)
    exp_stats  = exp_stats.sort_values('experience_level').dropna()
    exp_chart  = {
        'labels':   exp_stats['experience_level'].tolist(),
        'salaries': [int(x) for x in exp_stats['salary_in_usd'].tolist()],
    }

    # Remote Ratio
    remote_stats = df['remote_status'].value_counts().reset_index()
    remote_stats.columns = ['status', 'count']
    remote_chart = {
        'labels': remote_stats['status'].tolist(),
        'counts': remote_stats['count'].tolist(),
    }

    # Salary by Year
    year_stats = df.groupby('work_year')['salary_in_usd'].mean().reset_index().sort_values('work_year')
    year_chart = {
        'labels':   year_stats['work_year'].tolist(),
        'salaries': [int(x) for x in year_stats['salary_in_usd'].tolist()],
    }

    # Top 5 Hiring Locations
    loc_stats = df['company_location_full'].value_counts().head(5).reset_index()
    loc_stats.columns = ['location', 'count']
    loc_chart = {
        'labels': loc_stats['location'].tolist(),
        'counts': loc_stats['count'].tolist(),
    }

    # Volume by Experience
    vol_stats = df['experience_level'].value_counts().reset_index()
    vol_stats.columns = ['exp', 'count']
    vol_chart = {
        'labels': vol_stats['exp'].tolist(),
        'counts': vol_stats['count'].tolist(),
    }

    return jsonify({
        'summary':      summary,
        'roles_chart':  roles_chart,
        'exp_chart':    exp_chart,
        'remote_chart': remote_chart,
        'year_chart':   year_chart,
        'loc_chart':    loc_chart,
        'vol_chart':    vol_chart,
    })


@app.route('/api/top_roles')
def top_roles():
    df = get_data()
    df = apply_global_filters(df, request.args)
    if df.empty or 'job_title' not in df.columns or 'salary_in_usd' not in df.columns:
        return jsonify({'labels': [], 'counts': [], 'avg_salaries': []})
    
    limit = int(request.args.get('limit', 10))

    role_counts = df['job_title'].value_counts().head(limit).reset_index()
    role_counts.columns = ['role', 'count']

    role_salary = (
        df.groupby('job_title')['salary_in_usd']
        .mean().round(0).astype(int).reset_index()
    )
    role_salary.columns = ['role', 'avg_salary']

    merged = role_counts.merge(role_salary, on='role')
    return jsonify({
        'labels':       merged['role'].tolist(),
        'counts':       merged['count'].tolist(),
        'avg_salaries': merged['avg_salary'].tolist(),
    })


@app.route('/api/jobs_table')
def jobs_table():
    df = get_data()
    df = apply_global_filters(df, request.args)

    year    = request.args.get('year')
    country = request.args.get('country')
    role    = request.args.get('role')
    min_sal = request.args.get('min_sal')

    if year and year != 'All':
        df = df[df['work_year'] == int(year)]
    if country and country != 'All':
        df = df[df['company_location_full'] == country]
    if role and role != 'All':
        df = df[df['job_title'].str.contains(role, case=False, na=False)]
    if min_sal and min_sal.strip():
        try:
            df = df[df['salary_in_usd'] >= int(min_sal)]
        except ValueError:
            pass

    if df.empty:
        return jsonify([])

    cols = [
        'work_year', 'job_title', 'experience_level', 'employment_type',
        'salary_in_usd', 'company_location_full', 'remote_status'
    ]
    records = df.sort_values('work_year', ascending=False)[cols].head(500).to_dict(orient='records')
    return jsonify(records)


@app.route('/api/country_avg_salary')
def country_avg_salary():
    df = get_data()
    df = apply_global_filters(df, request.args)
    if df.empty or 'company_location_full' not in df.columns or 'salary_in_usd' not in df.columns:
        return jsonify({'labels': [], 'salaries': []})

    year = request.args.get('year')
    if year and year != 'All':
        df = df[df['work_year'] == int(year)]

    # ?limit=10 (default), ?limit=0 means all countries
    limit = request.args.get('limit', 10, type=int)

    if df.empty:
        return jsonify({})

    c_stats = df.groupby('company_location_full').agg(
        avg_sal=('salary_in_usd', 'mean'),
        count=('salary_in_usd', 'count')
    ).reset_index()

    c_stats = c_stats[c_stats['count'] >= 3]
    top_c   = c_stats.sort_values('avg_sal', ascending=False)
    if limit > 0:
        top_c = top_c.head(limit)

    return jsonify({
        'labels':   top_c['company_location_full'].tolist(),
        'salaries': [int(x) for x in top_c['avg_sal'].tolist()],
    })


@app.route('/api/underpaid_calculator/<role>/<experience>/<current_salary>')
def underpaid_calculator(role, experience, current_salary):
    df = get_data()
    if df.empty:
        return jsonify({'error': 'No data'})

    try:
        current_salary = float(current_salary)
    except ValueError:
        return jsonify({'error': 'Invalid salary'})

    # Optional country context (e.g. ?country=India)
    country = request.args.get('country')

    base_match = df[
        (df['job_title'].str.contains(role, case=False, na=False)) &
        (df['experience_level'] == experience)
    ]

    matching = base_match
    if country and country != 'All':
        country_match = base_match[base_match['company_location_full'] == country]
        if len(country_match) >= 3:
            matching = country_match
        else:
            # Fall back to global if country has too few data points
            country = None

    if len(matching) == 0:
        return jsonify({
            'status':  'Unknown',
            'message': 'Not enough data for this role / experience level.'
        })

    market_avg  = matching['salary_in_usd'].mean()
    diff        = current_salary - market_avg
    diff_pct    = (diff / market_avg) * 100

    status = 'Fairly Paid'
    if diff_pct < -10:
        status = 'Underpaid'
    elif diff_pct > 10:
        status = 'Overpaid'

    return jsonify({
        'status':          status,
        'market_average':  int(market_avg),
        'difference':      int(abs(diff)),
        'message':         f"Market Avg: ${int(market_avg):,}. You are {status} by ~{int(abs(diff_pct))}%.",
        'sample_count':    len(matching),
        'country_context': country if country else 'Global',
    })


# ═══════════════════════════════════════════════════════════════════
#  LIVE DATA MODULE  —  /live  (does NOT touch any existing routes)
# ═══════════════════════════════════════════════════════════════════
_live_cache = {'data': None, 'ts': 0}
LIVE_TTL    = 3600   # refresh every 1 hour

# Category keyword mapping
CATEGORY_MAP = [
    ('Data / ML / AI',       ['data scientist','machine learning','data engineer','data analyst',
                               'ml engineer','ai engineer','analytics engineer','deep learning',
                               'nlp engineer','llm','data science','computer vision','bi analyst']),
    ('Software Engineering', ['software engineer','backend','frontend','full stack','fullstack',
                               'developer','programmer','web developer','java developer',
                               'python developer','node','react developer','mobile developer']),
    ('DevOps / Cloud / SRE', ['devops','cloud engineer','aws','azure','gcp','kubernetes',
                               'docker','sre','site reliability','infrastructure','platform engineer']),
    ('Product / Project',    ['product manager','project manager','product owner',
                               'scrum master','agile coach','program manager']),
    ('Design / UX',          ['designer','ux designer','ui designer','graphic designer',
                               'product designer','visual designer']),
    ('Marketing / Growth',   ['marketing','growth hacker','seo','content writer',
                               'copywriter','social media','digital marketing']),
    ('Finance / Accounting', ['finance','accountant','financial analyst','bookkeeper',
                               'controller','cfo','revenue operations']),
    ('Sales / CRM',          ['sales','account executive','business development',
                               'crm','account manager','sales engineer']),
    ('HR / Recruiting',      ['recruiter','human resources','hr manager',
                               'talent acquisition','people operations']),
    ('Customer / Support',   ['customer success','customer support','support engineer',
                               'help desk','technical support']),
]

def _detect_category(title):
    tl = title.lower()
    for cat, keywords in CATEGORY_MAP:
        if any(k in tl for k in keywords):
            return cat
    return 'Other'

def _parse_salary(s):
    """Parse salary strings like '$50k-$80k', '80000', '100k' → average int or None."""
    if not s:
        return None
    cleaned = re.sub(r'[£€,\s]', '', s).replace('$', '').lower()
    nums = re.findall(r'[\d]+(?:\.\d+)?k?', cleaned)
    vals = []
    for n in nums:
        try:
            v = float(n.rstrip('k')) * (1000 if n.endswith('k') else 1)
            if 500 < v < 10_000_000:
                vals.append(v)
        except ValueError:
            pass
    return round(sum(vals) / len(vals)) if vals else None

def _time_ago(date_str):
    if not date_str:
        return 'Unknown'
    try:
        # Manual parsing for python 3.6 compatibility
        clean = date_str.split('.')[0].replace('Z', '').replace('T', ' ')
        if len(clean) == 10:
            dt = datetime.strptime(clean, '%Y-%m-%d')
        else:
            dt = datetime.strptime(clean, '%Y-%m-%d %H:%M:%S')
    except Exception:
        return date_str
            
    now = datetime.utcnow()
    diff = now - dt
    
    if diff.days > 365:
        return f"{diff.days // 365} years ago"
    if diff.days > 30:
        return f"{diff.days // 30} months ago"
    if diff.days > 0:
        return f"{diff.days} days ago"
    
    hours = diff.seconds // 3600
    if hours > 0:
        return f"{hours} hours ago"
    
    mins = diff.seconds // 60
    if mins > 0:
        return f"{mins} mins ago"
        
    return "just now"

def _fetch_remoteok():
    jobs = []
    try:
        r = req_lib.get(
            'https://remoteok.com/api',
            headers={'User-Agent': 'DataVista/1.0 (job analytics research)'},
            timeout=14
        )
        r.raise_for_status()
        raw = r.json()
        for item in raw[1:]:         # index 0 is metadata
            if not isinstance(item, dict):
                continue
            title = (item.get('position') or '').strip()
            if not title:
                continue
            sal_min = item.get('salary_min') or 0
            sal_max = item.get('salary_max') or 0
            if sal_min and sal_max:
                sal_avg = int((sal_min + sal_max) / 2)
            elif sal_min or sal_max:
                sal_avg = int(sal_min or sal_max)
            else:
                sal_avg = None
                
            raw_date = str(item.get('date') or '')
            
            jobs.append({
                'title':    title,
                'company':  (item.get('company') or '').strip(),
                'salary':   sal_avg,
                'tags':     [t.lower() for t in (item.get('tags') or [])][:10],
                'date':     _time_ago(raw_date),
                'source':   'RemoteOK',
                'url':      item.get('url', ''),
                'location': (item.get('location') or 'Remote').strip() or 'Remote',
                'category': _detect_category(title),
            })
    except Exception as ex:
        print(f'[LIVE] RemoteOK failed: {ex}')
    return jobs

def _fetch_remotive():
    jobs = []
    try:
        r = req_lib.get('https://remotive.com/api/remote-jobs', timeout=14)
        r.raise_for_status()
        raw = r.json().get('jobs', [])
        for item in raw:
            title = (item.get('title') or '').strip()
            if not title:
                continue
            sal_raw = item.get('salary') or ''
            tags    = [t.strip().lower() for t in (item.get('tags') or [])][:10]
            
            raw_date = str(item.get('publication_date') or '')
            
            jobs.append({
                'title':    title,
                'company':  (item.get('company_name') or '').strip(),
                'salary':   _parse_salary(sal_raw),
                'tags':     tags,
                'date':     _time_ago(raw_date),
                'source':   'Remotive',
                'url':      item.get('url', ''),
                'location': 'Remote',
                'category': _detect_category(title),
            })
    except Exception as ex:
        print(f'[LIVE] Remotive failed: {ex}')
    return jobs

def get_live_data(force=False):
    global _live_cache
    now = time.time()
    if not force and _live_cache and (now - _live_cache['ts'] < 3600):
        return _live_cache['data']
        
    jobs = []
    
    # Fetch from RemoteOK
    try:
        jobs.extend(_fetch_remoteok())
    except Exception as e:
        print(f"[WARN] RemoteOK API failed: {e}")
        
    # Fetch from Remotive
    try:
        jobs.extend(_fetch_remotive())
    except Exception as e:
        print(f"[WARN] Remotive API failed: {e}")
        
    if not jobs:
        # If both fail, and we have an old cache, return the old cache instead of an error
        if _live_cache.get('data'):
            return _live_cache['data']
        return {"error": "Live data temporarily unavailable. Both RemoteOK and Remotive APIs are currently unreachable or rate-limiting requests."}

    _live_cache = {'data': jobs, 'ts': now}
    print(f'[LIVE] Fetched {len(jobs)} live jobs total')
    return jobs


@app.route('/live')
def live_page():
    return send_from_directory('static', 'live.html')


@app.route('/api/live/stats')
def live_stats():
    jobs = get_live_data()
    if isinstance(jobs, dict) and 'error' in jobs:
        return jsonify({'error': jobs['error']})
    if not jobs:
        return jsonify({'error': 'Live data temporarily unavailable. APIs may be down.'})

    total       = len(jobs)
    with_salary = [j for j in jobs if j['salary']]
    avg_sal     = int(sum(j['salary'] for j in with_salary) / len(with_salary)) if with_salary else 0
    max_sal     = max((j['salary'] for j in with_salary), default=0)

    # Category distribution
    cat_cnt = {}
    for j in jobs:
        cat_cnt[j['category']] = cat_cnt.get(j['category'], 0) + 1
    top_cats = sorted(cat_cnt.items(), key=lambda x: x[1], reverse=True)

    # Top skills from tags
    NOISE = {'full-time','part-time','contract','remote','senior','junior','lead',
              'manager','engineer','developer','design','marketing','sales','finance'}
    skill_cnt = {}
    for j in jobs:
        for t in j['tags']:
            if len(t) > 1 and t not in NOISE:
                skill_cnt[t] = skill_cnt.get(t, 0) + 1
    top_skills = sorted(skill_cnt.items(), key=lambda x: x[1], reverse=True)[:15]

    # Top hiring companies
    co_cnt = {}
    for j in jobs:
        if j['company']:
            co_cnt[j['company']] = co_cnt.get(j['company'], 0) + 1
    top_cos = sorted(co_cnt.items(), key=lambda x: x[1], reverse=True)[:10]

    # Salary by category
    cat_sal = {}
    for j in with_salary:
        cat_sal.setdefault(j['category'], []).append(j['salary'])
    cat_sal_avg = sorted(
        [(c, int(sum(v)/len(v))) for c, v in cat_sal.items() if v],
        key=lambda x: x[1], reverse=True
    )[:8]

    # Source breakdown
    src_cnt = {}
    for j in jobs:
        src_cnt[j['source']] = src_cnt.get(j['source'], 0) + 1

    last_upd = datetime.fromtimestamp(_live_cache['ts']).strftime('%d %b %Y, %H:%M') \
               if _live_cache['ts'] else 'Never'

    return jsonify({
        'total_jobs':    total,
        'with_salary':   len(with_salary),
        'avg_salary':    avg_sal,
        'max_salary':    max_sal,
        'top_category':  top_cats[0][0] if top_cats else 'N/A',
        'top_categories': [{'label': k, 'count': v} for k, v in top_cats[:10]],
        'top_skills':     [{'label': k, 'count': v} for k, v in top_skills],
        'top_companies':  [{'label': k, 'count': v} for k, v in top_cos],
        'cat_salaries':   [{'label': k, 'salary': v} for k, v in cat_sal_avg],
        'sources':        [{'label': k, 'count': v} for k, v in src_cnt.items()],
        'last_updated':   last_upd,
    })


@app.route('/api/live/jobs')
def live_jobs():
    jobs = get_live_data()
    if isinstance(jobs, dict) and 'error' in jobs:
        return jsonify({'error': jobs['error']})
    if not jobs:
        return jsonify({'error': 'Live data temporarily unavailable. APIs may be down.'})
    category = request.args.get('category')
    skill    = request.args.get('skill')
    source   = request.args.get('source')

    filtered = jobs
    if category and category != 'All':
        filtered = [j for j in filtered if j['category'] == category]
    if skill and skill != 'All':
        filtered = [j for j in filtered if skill.lower() in j['tags']]
    if source and source != 'All':
        filtered = [j for j in filtered if j['source'] == source]

    filtered = sorted(filtered, key=lambda j: j['date'], reverse=True)
    return jsonify({'jobs': filtered[:400], 'total': len(filtered)})


@app.route('/api/live/refresh')
def live_refresh():
    jobs = get_live_data(force=True)
    return jsonify({'status': 'ok', 'count': len(jobs)})


if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    app.run(debug=True, port=5000)
