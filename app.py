import os
import time
import hmac
import secrets
from collections import defaultdict
from datetime import datetime
from urllib.parse import quote
from flask import (Flask, Blueprint, render_template, request, redirect,
                   flash, session, abort, url_for)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///trino.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Private admin area. CHANGE BOTH of these on your live server (set as environment variables).
ADMIN_PATH = os.environ.get('ADMIN_PATH', '/tw-admin-x7k2q9').rstrip('/')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'change-this-password')

UPLOAD_DIR = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)
STATUSES = ['New', 'Contacted', 'Won', 'Lost']
db = SQLAlchemy(app)


class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    package = db.Column(db.String(40), default='')
    details = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='New')
    created = db.Column(db.DateTime, default=datetime.now)


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    features = db.Column(db.Text, default='')   # one per line
    tags = db.Column(db.String(200), default='')
    link = db.Column(db.String(255), default='')
    images = db.Column(db.Text, default='')     # comma-separated paths inside /static

    @property
    def image_list(self):
        return [i for i in self.images.split(',') if i]

    @property
    def feature_list(self):
        return [f.strip() for f in self.features.splitlines() if f.strip()]


with app.app_context():
    db.create_all()
    if Project.query.count() == 0:   # first run: add Planet of Style
        db.session.add(Project(
            title='Planet of Style',
            description='A live online thrift store. Customers browse clothing and footwear by category and order directly on WhatsApp. The owner adds and manages stock from a private dashboard.',
            features='Category pages for jackets, shirts, trousers, footwear and accessories\nProduct pages with size, condition and price in kwacha\nOne-tap WhatsApp order message that fills in the item details\nPrivate admin login with lockout after repeated wrong passwords\nAdd items with photo upload, mark them sold, or delete them',
            tags='Python · Flask · SQLAlchemy · SQLite · HTML · CSS',
            link='https://trinowanda.pythonanywhere.com',
            images='img/store.jpg,img/admin.jpg'))
        db.session.commit()

WHATSAPP_NUMBER = os.environ.get('WHATSAPP_NUMBER', '260769882152')  # digits only, with country code
CONTACT_EMAIL = os.environ.get('CONTACT_EMAIL', 'andrewmulaliki2002@gmail.com')

PACKAGES = [
    {'name': 'Starter', 'price': 1500, 'split': 'K750 to start, K750 on handover', 'popular': False,
     'features': ['1-3 pages', 'Mobile responsive design', 'WhatsApp button', 'Contact section', 'Basic deployment']},
    {'name': 'Business', 'price': 3500, 'split': 'K1,500 + K1,000 + K1,000', 'popular': True,
     'features': ['Up to 6 pages', 'Custom website design', 'Mobile responsive', 'Contact form',
                  'WhatsApp integration', 'Basic SEO', 'Website deployment',
                  'Admin dashboard to manage content']},
    {'name': 'Business Pro', 'price': 6000, 'split': 'K2,500 + K1,500 + K2,000', 'popular': False,
     'features': ['Everything in Business', 'Advanced admin dashboard / CMS', 'Database integration',
                  'Product and content management', 'Add, edit and delete records',
                  'User authentication', 'Advanced custom functionality']},
]

STEPS = [
    ('Initial deposit', 'You pay the first installment and development begins.'),
    ('Development milestone', 'Once the agreed milestone is reached, the next installment is paid before the remaining work continues.'),
    ('Launch and handover', 'You review the finished site and pay the final installment. Then credentials and source-code ownership are transferred to you.'),
]

TERMS = [
    'Features outside your package are quoted separately.',
    'Domain, hosting and major third-party services are charged separately unless agreed otherwise.',
    'Work may be paused if an installment is overdue.',
    'Pay by MTN Money, Airtel Money, Zamtel Kwacha or bank transfer.',
]


@app.template_filter('kwacha')
def kwacha(n):
    return f'K{n:,.0f}'


@app.route('/')
def home():
    return render_template('index.html', packages=PACKAGES, steps=STEPS, terms=TERMS,
                           email=CONTACT_EMAIL, projects=Project.query.order_by(Project.id).all())


@app.route('/quote', methods=['POST'])
def quote_request():
    name = request.form.get('name', '').strip()[:80]
    package = request.form.get('package', '').strip()[:40]
    details = request.form.get('details', '').strip()[:600]
    if not name or not details:
        flash('Please enter your name and a short description of what you need.')
        return redirect('/#contact')
    db.session.add(Lead(name=name, package=package, details=details))
    db.session.commit()
    msg = (f"Hi Trino Wanda Web Services, I'm {name}.\n"
           f"Package: {package or 'Not sure yet'}\n\n{details}")
    return redirect(f'https://wa.me/{WHATSAPP_NUMBER}?text={quote(msg)}')


# ---------------------------------------------------------------------------
# PRIVATE ADMIN  (secret URL; looks like a 404 to anyone who is not logged in)
# ---------------------------------------------------------------------------
admin = Blueprint('admin', __name__, url_prefix=ADMIN_PATH)
_failed = defaultdict(list)
MAX_TRIES, WINDOW = 5, 15 * 60


def csrf():
    session.setdefault('csrf', secrets.token_hex(16))
    return session['csrf']


app.jinja_env.globals['csrf'] = csrf


def guard():
    if session.get('is_admin') is not True:
        abort(404)
    if request.method == 'POST' and not hmac.compare_digest(
            request.form.get('csrf', ''), session.get('csrf', 'x')):
        abort(400)


@admin.after_request
def no_indexing(resp):
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@admin.route('/', methods=['GET', 'POST'], strict_slashes=False)
def panel():
    if session.get('is_admin') is not True:
        if request.method == 'POST':
            ip = request.remote_addr or 'unknown'
            now = time.time()
            _failed[ip] = [t for t in _failed[ip] if now - t < WINDOW]
            if len(_failed[ip]) >= MAX_TRIES:
                flash('Too many attempts. Try again in 15 minutes.')
            elif hmac.compare_digest(request.form.get('password', '').encode(), ADMIN_PASSWORD.encode()):
                session.clear()
                session['is_admin'] = True
                return redirect(url_for('admin.panel'))
            else:
                _failed[ip].append(now)
                flash('Incorrect password.')
        return render_template('admin.html', logged_in=False)
    if request.method == 'POST':
        abort(405)
    return render_template('admin.html', logged_in=True, statuses=STATUSES,
                           leads=Lead.query.order_by(Lead.id.desc()).all(),
                           projects=Project.query.order_by(Project.id).all())


@admin.route('/lead/<int:lead_id>/status', methods=['POST'])
def lead_status(lead_id):
    guard()
    lead = db.get_or_404(Lead, lead_id)
    status = request.form.get('status')
    if status in STATUSES:
        lead.status = status
        db.session.commit()
    return redirect(url_for('admin.panel') + '#leads')


@admin.route('/lead/<int:lead_id>/delete', methods=['POST'])
def lead_delete(lead_id):
    guard()
    db.session.delete(db.get_or_404(Lead, lead_id))
    db.session.commit()
    return redirect(url_for('admin.panel') + '#leads')


@admin.route('/project/add', methods=['POST'])
def project_add():
    guard()
    title = request.form.get('title', '').strip()[:100]
    description = request.form.get('description', '').strip()
    if not title or not description:
        flash('A project needs a title and a description.')
        return redirect(url_for('admin.panel') + '#projects')
    images = []
    for f in request.files.getlist('images'):
        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
        if f.filename and ext in {'png', 'jpg', 'jpeg', 'webp'}:
            name = f"{int(time.time() * 1000)}_{secure_filename(f.filename)}"
            f.save(os.path.join(UPLOAD_DIR, name))
            images.append('uploads/' + name)
    link = request.form.get('link', '').strip()[:255]
    if link and not link.startswith(('http://', 'https://')):
        link = 'https://' + link
    db.session.add(Project(title=title, description=description,
                           features=request.form.get('features', ''),
                           tags=request.form.get('tags', '').strip()[:200],
                           link=link, images=','.join(images)))
    db.session.commit()
    flash('Project added.')
    return redirect(url_for('admin.panel') + '#projects')


@admin.route('/project/<int:project_id>/delete', methods=['POST'])
def project_delete(project_id):
    guard()
    db.session.delete(db.get_or_404(Project, project_id))
    db.session.commit()
    return redirect(url_for('admin.panel') + '#projects')


@admin.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect('/')


app.register_blueprint(admin)


@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404


if __name__ == '__main__':
    print('Admin dashboard: http://127.0.0.1:5000' + ADMIN_PATH)
    app.run(debug=True)
