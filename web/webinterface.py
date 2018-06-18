import logging
import os
import random
import string
from datetime import datetime
from flask import Flask, render_template, redirect, session, request, flash, url_for
from flaskext.mysql import MySQL
from passlib.hash import argon2

from main import Device

device = Device()

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger("FLASK_LOG")

app = Flask(__name__)
app.secret_key = os.urandom(32)
mysql = MySQL()

# MySQL configurations
app.config['MYSQL_DATABASE_USER'] = 'ufee-admin'
app.config['MYSQL_DATABASE_PASSWORD'] = 'adminpassword'
app.config['MYSQL_DATABASE_DB'] = 'ufee'
app.config['MYSQL_DATABASE_HOST'] = 'localhost'
mysql.init_app(app)

# Default sound -- override when sound is given
snd = None
player = None


# ---------------------
# BASIC CRUD FUNCTIONS
# ---------------------
def get_data(sql, params=None):
    conn = mysql.connect()
    cursor = conn.cursor()
    records = []

    try:
        log.info(sql)
        cursor.execute(sql, params)
        result = cursor.fetchall()
        for row in result:
            records.append(list(row))

    except Exception as e:
        log.error("Error on fetching data: {0})".format(e))

    cursor.close()
    conn.close()

    return records


def set_data(sql, params=None):
    conn = mysql.connect()
    cursor = conn.cursor()

    try:
        log.info(sql)
        cursor.execute(sql, params)
        conn.commit()
        log.info("SQL executed")

    except Exception as e:
        log.error("Error on executing SQL: {0})".format(e))
        return False

    cursor.close()
    conn.close()

    return True


# --------------
# CREATE
# --------------
def create_user(username, password, password_repeat):
    # CHECK INPUT
    validation = validate_user_input(username, password, password_repeat)
    if not validation[0]:
        return validation
    # CREATE PASSWORD HASH
    salt = get_salt()
    pwd_string = "{}{}".format(password, salt)
    pw_hash = argon2.hash(pwd_string)
    # EXECUTE
    if set_data("insert into `users` (`username`, `hash`, `salt`) values (%s, %s, %s)", [username, pw_hash, salt, ]):
        return [True, "User has been succesfully created, login to continue!"]
    return [False, "An unexpected error has occurred, try again later!"]


def create_coffee(name, amt_water, amt_coffee, public=1):
    # CHECK INPUT
    validation = validate_coffee_input(name, amt_water, amt_coffee)
    if not validation[0]:
        log.debug("CREATE COFFEE: INVALID INPUT!!!")
        return validation
    # EXECUTE
    if set_data("insert into  `coffees` (`name`, `amt_water`, `amt_coffee`, `username`, `public`) "
                "values (%s, %s, %s, %s, %s)",
                [name.title(), amt_water, amt_coffee, session['username'], public, ]):
        return [True, "Coffee successfully created!"]
    log.debug("CREATE COFFEE: UNEXPECTED ERROR!!!")
    return [False, "An unexpected error has occurred, try again later!"]


def create_alarm(hour, minutes, song_id, coffee_id):
    log.debug("CALLED CREATE_ALARM()")
    # CHECK INPUT
    validation = validate_alarm_input(hour, minutes, song_id, coffee_id)
    if not validation[0]:
        return validation
    # EXECUTE
    if set_data("insert into `alarms` (hour, minutes, songID, coffeeID, username) "
                "values (%s, %s, %s, %s, %s)",
                [hour, minutes, song_id, coffee_id, session['username'], ]):
        device.update_alarm()
        return [True, "Alarm successfully created!"]
    log.debug("CREATE ALARM: UNEXPECTED ERROR!!!")
    return [False, "An unexpected error has occurred, try again later!"]


def create_alarm_day(alarm_id, day_id):
    validation = validate_alarm_day_input(alarm_id, day_id)
    if not validation[0]:
        return validation
    # EXECUTE
    if set_data("insert into `alarmDays` "
                "(alarmID, dayID) "
                "values (%s, %s)",
                [alarm_id, day_id]):
        return [True, "Day has successfully been added to the alarm"]
    return [False, "An unexpected error has occurred, try again later!"]


def create_log(coffee_id):
    if not get_coffee(coffee_id):
        return [False, "Coffee does not exist"]
    dt = datetime.now()
    if set_data("insert into `brew_history` "
                "(`username`, `coffeeID`, `date` )"
                "values (%s, %s, %s)",
                [session['username'], coffee_id, "{}-{}-{}".format(dt.year, dt.month, dt.day)]):
        return [True, "Log has been successfully added"]
    return [False, "An unexpected error has occurred, try again later!"]


def upload_song():
    ...


# --------------
# READ
# --------------
def username_available(username):
    val = get_data("select `username` "
                   "from `users` "
                   "where `username` = %s;",
                   [username, ])
    if not val:
        return True
    return False


def coffee_name_available(coffee_name):
    val = get_data("select coffeeID "
                   "from coffees "
                   "where name = %s",
                   [coffee_name, ])

    if not val:
        return True
    return False


def validate_user(username, password):
    data = get_data("select username, hash, salt, role "
                    "from users "
                    "where username = %s",
                    [username, ])

    if not data:
        return False
    data = data[0]
    verify = argon2.verify(password + data[2], data[1])
    if verify:
        session['username'] = data[0]
        session['role'] = data[3]
        return True
    return False


def get_user(username):
    return get_data("select username, hash, salt, role "
                    "from users "
                    "where username = %s",
                    [username, ])


def get_last_seven_days():
    return get_data("select date, count(BrewID) from brew_history "
                    "where username = %s"
                    "group by date "
                    "order by date ASC ",
                    [session['username']])


def get_top_three_coffees():
    total = get_data("select count(brewID) "
                     "from brew_history "
                     "where username = %s",
                     [session['username'], ])

    data = get_data("select C.name, count(B.coffeeID) "
                    "from brew_history as B "
                    "join coffees as C "
                    "on B.coffeeID = C.coffeeID "
                    "where B.username = %s "
                    "group by C.name "
                    "order by count(B.coffeeID) "
                    "DESC LIMIT 3",
                    [session['username'], ])

    for line in data:
        line[1] = line[1] / total[0][0] * 100
    return data


def get_coffees():
    if is_admin():
        return get_data("select coffeeID, name, amt_water, amt_coffee, username "
                        "from coffees "
                        "order by name ASC;")

    return get_data("select coffeeID, name, amt_water, amt_coffee, username "
                    "from coffees "
                    "where public = 1 "
                    "or username = %s "
                    "order by name ASC;",
                    [session['username'], ])


def get_coffee(coffee_id):
    return get_data("select name, "
                    "amt_water, "
                    "amt_coffee, "
                    "username, "
                    "public "
                    "from coffees "
                    "where coffeeID = %s;",
                    [coffee_id, ])


def get_alarms():
    if is_admin():
        return get_data("select alarmID, hour, minutes, active, songID, coffeeID "
                        "from alarms;")

    return get_data("select alarmID, hour, minutes, active, songID, coffeeID "
                    "from alarms "
                    "where username = %s",
                    [session['username'], ])


def get_alarm(alarm_id):
    if is_admin():
        return get_data("select alarmID, hour, minutes, active, songID, coffeeID, username "
                        "from alarms "
                        "where alarmID = %s",
                        [alarm_id, ])

    return get_data("select alarmID, hour, minutes, active, songID, coffeeID, username "
                    "from alarms "
                    "where alarmID = %s "
                    "and username = %s",
                    [alarm_id, session['username'], ])


def get_next_alarm():
    today = datetime.today().weekday() + 1
    if today == 7:
        tomorrow = 1
    else:
        tomorrow = today + 1
    curr_hour = datetime.now().hour
    curr_min = datetime.now().minute
    next_alarm = False
    log.debug("NEXT ALARM: TODAY = {} AND TOMORROW = {}".format(today, tomorrow))

    next_alarms = get_data("select A.alarmID, A.hour, A.minutes, D.dayID from alarms as A "
                           "join alarmDays as D "
                           "on A.alarmID = D.alarmID "
                           "where (D.dayID = %s "
                           "or D.dayID = %s) "
                           "and A.active = 1 "
                           "order by D.dayID ASC, "
                           "A.hour ASC, "
                           "A.minutes ASC,"
                           "A.alarmID ASC",
                           [today, tomorrow, ])

    for a in next_alarms:
        log.debug("NEXT ALARM LOOP: {}-{}-{}".format(a[3], a[1], a[2]))
        if a[3] == today:
            if a[1] > curr_hour or (a[1] == curr_hour and a[2] > curr_min):
                next_alarm = a
                break
            continue
        next_alarm = a
        break

    return next_alarm


def get_alarm_days(alarm_id):
    days = get_data("select dayID "
                    "from alarmDays "
                    "where alarmID = %s",
                    [alarm_id, ])

    if days:
        vl = []
        for day in days:
            vl.append(day[0])
        return vl
    return days


def get_alarm_day(alarm_id, day_id):
    return get_data("select alarmID, dayID "
                    "from alarmDays "
                    "where alarmID = %s "
                    "and dayID = %s;",
                    [alarm_id, day_id])


def get_songs():
    if is_admin():
        return get_data("select songID, title, artist, filename, public "
                        "from songs;")

    return get_data("select songID, title, artist, filename, public "
                    "from songs "
                    "where username = %s or public = 1;",
                    [session['username'], ])


def get_song(song_id):
    return get_data("select title, artist, filename, public, username "
                    "from songs "
                    "where songID = %s",
                    [song_id, ])


# --------------
# UPDATE
# --------------
def update_coffee(coffee_id, name, amt_water, amt_coffee, public):
    # fetch coffee
    c = get_coffee(coffee_id)
    if not c:
        log.debug("UPDATE COFFEE: COFFEE NOT FOUND!!!")
        return [False, "Coffee not found!"]
    # input validation
    validation = validate_coffee_input(name, amt_water, amt_coffee, coffee_id)
    if not validation[0]:
        log.debug("UPDATE COFFEE: INVALID INPUT!!!")
        return validation
    # check authentication and execute accordingly
    if c[0][3] == session['username'] or is_admin():
        success = set_data("update coffees "
                           "set `name` = %s, "
                           "`amt_water` = %s, "
                           "`amt_coffee` = %s, "
                           "`public` = %s "
                           "where `coffeeID` = %s",
                           [name.title(), amt_water, amt_coffee, public, coffee_id])
        if success:
            log.debug("UPDATE COFFEE: COFFEE UPDATED!!!")
            return [True, "Coffee successfully updated!"]
        else:
            log.debug("UPDATE COFFEE: UNEXPECTED ERROR!!!")
            return [False, "Unexpected error, try again!"]
    log.debug("UPDATE COFFEE: UNAUTHORIZED")
    return [False, "Unauthorized to edit coffee!"]


def update_alarm(alarm_id, hour, minutes, active, song_id, coffee_id):
    # fetch alarm
    a = get_alarm(alarm_id)
    # input validation
    validation = validate_alarm_input(hour, minutes, song_id, coffee_id)
    if not validation[0]:
        return validation
    # check authentication and execute accordingly
    if a[0][5] == session['username'] or is_admin():
        success = set_data("update alarms "
                           "set `hour` = %s, "
                           "`minutes` = %s, "
                           "`active` = %s, "
                           "`songID` = %s, "
                           "`coffeeID` = %s "
                           "where alarmID = %s",
                           [hour, minutes, active, song_id, coffee_id, alarm_id, ])
        device.update_alarm()
        return success
    return [False, "Unauthorized to update alarm"]


def update_password(username, password):
    if session['username'] == username or is_admin():
        user = get_user(username)
        if user:
            log.debug(user[0][2])
            password_string = "{}{}".format(password, user[0][2])
            password_hash = argon2.hash(password_string)
            success = set_data("update users "
                               "set hash = %s "
                               "where username = %s",
                               [password_hash, username])
            return success
    return False


# --------------
# DELETE
# --------------
def delete_alarm_day(alarm_id, day_id):
    return set_data("delete from alarmDays "
                    "where alarmID = %s "
                    "and dayID = %s;",
                    [alarm_id, day_id])


def delete_alarm(alarm_id):
    return set_data("delete from alarms "
                    "where alarmID = %s",
                    [alarm_id, ])


# --------------
# INPUT VALIDATION
# --------------

def validate_user_input(username, password, password_repeat):
    if password != password_repeat:
        log.error("passwords don't match")
        return [False, "Passwords don't match, try again!"]
    if not username_available(username):
        log.error("username already exists")
        return [False, "Username already exists, pick another one!"]
    if len(password) < 5:
        log.error("password too short")
        return [False, "Password should be at least 5 characters long!"]
    return [True, "validation success"]


def validate_coffee_input(name, amt_water, amt_coffee, coffee_id=-1):
    if coffee_id == -1 or get_coffee(coffee_id)[0][0] != name:
        if not coffee_name_available(name):
            return [False, "There's already a coffee with the name {}, choose another name!".format(name)]
    if not 25 <= int(amt_water) <= 250:
        return [False, "Amount of water should be between 25 and 250ml"]
    if not 1 <= int(amt_coffee) <= 5:
        return [False, "Amount of coffee should be between 1 and 5 scoops"]
    if not 5 <= len(name) <= 25:
        return [False, "Length of name should be between 5 and 25 characters"]
    return [True, "validation success"]


def validate_alarm_input(hour, minutes, song_id, coffee_id):
    if not (24 >= int(hour) >= 0 and 59 >= int(minutes) >= 0):
        return [False, "Incorrect time input"]
    if not get_coffee(coffee_id):
        return [False, "The selected coffee doesn't exist!"]
    if not get_song(song_id):
        return [False, "The selected song doens't exist, try oploading it!"]
    return [True, "validation success"]


def validate_alarm_day_input(alarm_id, day_id):
    if not get_data("select alarmID from alarms where alarmID = %s",
                    [alarm_id]):
        return [False, "Alarm does not exist!"]
    if not 0 < int(day_id) < 8:
        return [False, "Invalid day!"]
    return [True, "validation success"]


# -------------------------------
# AUTHENTICATION & AUTHORIZATION
# -------------------------------

def logged_in():
    if 'username' in session:
        log.info("LOGGED IN!")
        return True
    log.info("NOT LOGGED IN!")
    return False


def is_admin():
    if session['role'] == "admin":
        return True
    return False


def get_salt():
    salt = ''
    # join(random.(string.ascii_letters + string.digits, k=16))
    chars = string.ascii_letters + string.digits
    for i in range(16):
        salt += chars[random.randint(0, len(chars) - 1)]
    log.info("salt = {}".format(salt))
    return salt


# -----------------
# CONTROLLERS MAIN
# -----------------
@app.route('/')
def index():
    if not logged_in():
        return redirect('login')
    top_three = get_top_three_coffees()
    history_overview = get_last_seven_days()
    data = get_coffees()
    ho_values = []
    top_three_values = []
    top_three_labels = []
    placeholder = "--"
    placeholder2 = "--/--/----"
    log.debug("CHECKING MACHINE STATE ######")
    state = device.machine_ready()
    for i in range(3):
        if len(top_three) >= i + 1:
            top_three_labels.append(top_three[i][0])
            top_three_values.append(top_three[i][1])
        else:
            top_three_labels.append(placeholder)
            top_three_values.append(0)

    for i in range(7):
        if len(history_overview) >= i + 1:
            dateobj = history_overview[i][0]
            if dateobj.day < 10:
                dateobj_day = "0{}".format(dateobj.day)
            else:
                dateobj_day = dateobj.day
            if dateobj.month < 10:
                dateobj_month = "0{}".format(dateobj.month)
            else:
                dateobj_month = dateobj.month
            date_string = "{}/{}/{}".format(dateobj_day, dateobj_month, dateobj.year)
            ho_values.append([date_string, history_overview[i][1]])
        else:
            ho_values.append([placeholder2, 0])
    print(history_overview)
    return render_template('index.html', data=data, top_three_values=top_three_values,
                           top_three_labels=top_three_labels, history_overview=ho_values, ready=state[0],
                           message=state[1])


@app.route('/login', methods=['GET', 'POST'])
def login():
    if logged_in():
        return redirect('/')
    if request.method == 'POST':
        usr = request.form.get('username')
        pw = request.form.get('password')
        if not validate_user(usr, pw):
            return render_template('login.html',
                                   error="The combination of username and password does not exist, try again!")
        return redirect('/')
    return render_template('login.html', error="")


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if logged_in():
        return redirect('/')
    if request.method == "POST":
        usr = request.form.get("username")
        pwd = request.form.get("password")
        pwr = request.form.get("password-repeat")
        val = create_user(usr, pwd, pwr)
        if val[0]:
            log.info("value = {}, redirecting to login".format(val[0]))
            return redirect('/login')
        else:
            return render_template('register.html', error=val[1])
    return render_template('register.html', error="")


@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if not logged_in():
        return redirect('login')
    if request.method == 'POST':
        password_old = request.form.get('password-old')
        password = request.form.get('password')
        password_repeat = request.form.get('password-repeat')
        if not password == password_repeat:
            return render_template('profile.html', error="password and password-repeat don't match!")
        if password == password_old:
            return render_template('profile.html', error="New password can't be the same as the old password!")
        if len(password) < 5:
            return render_template('profile.html', error="Password should be at least 5 characters long")
        if validate_user(session['username'], password_old):
            success = update_password(session['username'], password)
            if success:
                return render_template('profile.html', message="Password successfully changed")
            return render_template('profile.html', error="Oops! An unexpected error has occurred, try again later!")
        return render_template('profile.html', error="Password incorrect, try again!")
    return render_template('profile.html', error="", message="")


@app.route('/coffees')
def coffees():
    if not logged_in():
        return redirect('login')
    data = get_coffees()
    state = device.machine_ready()
    return render_template('coffees.html', data=data, ready=state[0], message=state[1])


@app.route('/alarms')
def alarms():
    if not logged_in():
        return redirect('login')
    # FETCHING NEXT ALARM
    next = get_next_alarm()
    log.debug("ALARMS: NEXT ALARM = {}".format(next))
    message = ""
    if next:
        if next[3] == datetime.today().weekday() + 1:
            dy = "today"
        else:
            dy = "tomorrow"
        minutes = next[2]
        if minutes < 10:
            minutes = "0" + str(minutes)
            tm = "{}:{}".format(next[1], minutes)
        else:
            tm = "{}:{}".format(next[1], minutes)
        message = "Next alarm {} at {}".format(dy, tm)
    # FETCHING ALL ALARMS
    data = get_alarms()
    # FETCHING DAYS, SONGS AND COFFEES FOR EACH ALARM
    days = []
    songs = []
    coffees = []
    for line in data:
        days.append(get_alarm_days(line[0]))
        song = get_song(line[4])
        # CHECK IF SONG IS SET (NOT MANDATORY)
        if song:
            songs.append(song[0])
        else:
            songs.append([])
        coffees.append(get_coffee(line[5])[0])
    log.debug("ALARMS: SONGS = {}".format(songs))
    log.debug("ALARMS: DAYS = {}".format(days))
    return render_template('alarms.html', data=data, days=days, songs=songs, coffees=coffees, message=message)


# --------------------s
# CONTROLLERS DETAIL
# --------------------
@app.route("/coffee", methods=['GET', 'POST'])
@app.route('/coffee/<coffee_id>', methods=['GET', 'POST'])
def coffee(coffee_id=None):
    if not logged_in():
        return redirect('login')

    if request.method == 'POST':
        log.debug("COFFEE_DETAIL: POST INFO FETCHED!!!")
        coffee_id = int(request.form.get('id'))
        name = request.form.get('name')
        amt_water = request.form.get('water')
        amt_coffee = request.form.get('coffee')
        public = request.form.get('public')
        # SET VALUE OF "PUBLIC" TO MATCH DATABASE FORMAT
        if public:
            public = 1
        else:
            public = 0
        log.debug("COFFEE DETAIL: PUBLIC VALUE = {}".format(public))
        # UPDATE OF CREATE
        if coffee_id == -1:
            log.debug("COFFEE_DETAIL: CREATING A NEW COFFEE!!!")
            success = create_coffee(name, amt_water, amt_coffee)
            flash(success[1])
        else:
            log.debug("COFFEE_DETAIL: UPDATING AN EXISTING COFFEE!!!")
            success = update_coffee(coffee_id, name, amt_water, amt_coffee, public)
            log.debug(success)
            flash(success[1])
        return redirect(url_for('coffees'))

    if coffee_id is None:
        return redirect('/coffees')

    data = []
    if coffee_id is not -1:
        data = get_coffee(coffee_id)
    return render_template('coffee-detail.html', data=data, id=coffee_id)


@app.route('/alarm/<alarm_id>', methods=['GET', 'POST'])
def alarm(alarm_id):
    if not logged_in():
        return redirect('login')

    if request.method == 'POST':
        btn_val = request.form.get('action')
        hour = request.form.get('hour')
        minutes = request.form.get('minutes')
        song_id = request.form.get('song_id')
        coffee_id = request.form.get('coffee_id')
        a_id = request.form.get('alarm_id')
        if btn_val == "save":
            # IF ID == -1
            if a_id == "-1":
                # CREATE NEW
                success = create_alarm(hour, minutes, song_id, coffee_id)
                if success[0]:
                    return redirect('alarms')
                log.debug("PROBLEM")
            else:
                # CALL UPDATE
                a = get_alarm(a_id)

                if a:
                    if a[0][6] == session['username'] or is_admin():
                        success = update_alarm(alarm_id, hour, minutes, a[0][3], song_id, coffee_id)
                        log.debug(success)
                    return redirect('alarms')

        else:
            if get_alarm_day(alarm_id, btn_val):
                delete_alarm_day(alarm_id, btn_val)
            else:
                create_alarm_day(alarm_id, btn_val)

    data = []
    song = []
    coffee = []
    days = []

    # FETCH ALL ALARM DATA IF NOT A NEW ALARM
    if not alarm_id == "-1":
        log.debug("ALARM-DETAIL: EXISTING ALARM!")
        data = get_alarm(alarm_id)
        if data == []:
            return redirect('alarms')
        data = data[0]
        song = get_song(data[4])[0]
        coffee = get_coffee(data[5])[0]
        days = get_alarm_days(data[0])

    coffees = get_coffees()
    songs = get_songs()
    return render_template('alarm-detail.html', data=data, song=song, coffee=coffee, days=days, coffees=coffees,
                           songs=songs)


# --------------------
# CONTROLLERS HANDLER
# --------------------
@app.route('/brew', methods=['GET', 'POST'])
def brew():
    if not logged_in():
        return redirect('login')
    if request.method == "POST":
        coffee_id = request.form.get('coffee')
        cff = get_coffee(coffee_id)[0]
        if not cff:
            session['message'] = "Coffee does not exist"
            return redirect('/')
        log.info("BREWING {}".format(cff[0]))
        flash("BREWING {}".format(cff[0]))
        if device.brew(cff[2], cff[1]):
            create_log(coffee_id)
    return redirect('/')


@app.route('/toggle_alarm', methods=['GET', 'POST'])
def toggle_alarm():
    if not logged_in():
        return redirect('login')
    if request.method == "POST":
        alarm_id = request.form.get('alarm_id')
        alr = get_alarm(alarm_id)
        if alr:
            update_alarm(alr[0][0], alr[0][1], alr[0][2], not alr[0][3], alr[0][4], alr[0][5])
            device.update_alarm()
    return redirect('/alarms')


# --------------------
# MAIN
# --------------------
if __name__ == '__main__':
    log.info("FLASK STARTED!")
    app.run(host="0.0.0.0")
