# CareCircle – Elderly Care & Medication Management Platform 💙

**CareCircle** is a healthcare coordination platform designed to make elderly care easier, safer, and more collaborative. It helps elderly individuals manage their daily medications, appointments, and health updates while allowing approved family members and caregivers to stay informed.

Our goal is to support independent living while keeping families connected and involved in elderly care.

---

## 📌 Problem Statement

Elderly individuals often face difficulties managing multiple medications, remembering appointments, and maintaining consistent health records.

At the same time, family members and caregivers may struggle to coordinate care, especially when they live in different locations.

This can lead to:
- Missed medications and delayed doses.
- Forgotten medical appointments.
- Lack of communication between family members and caregivers.
- Difficulty tracking daily health updates.
- Limited visibility into medication adherence.

## 💡 Our Solution

CareCircle provides a centralized platform where elderly users, caregivers, and approved family members can coordinate healthcare activities.

It focuses on medication management, timely reminders, health tracking, and controlled family access — helping make everyday elderly care more organized.

---

## ✨ Key Features

### 💊 1. Medication Management
- Add and manage medication schedules.
- Track taken, skipped, and pending doses.
- Monitor medication adherence.
- View upcoming and missed medication doses.

### 🔔 2. Smart Reminders & Notifications
- Medication reminders.
- Appointment notifications.
- Missed-dose alerts.
- Email notifications where configured.

### 👨‍👩‍👧 3. Family & Caregiver Collaboration
- Separate user roles for elderly individuals, caregivers, and family members.
- Family access requires elderly user approval.
- Read-only access for approved family members.
- Ability to revoke access.

### 📅 4. Appointment Management
- Manage medical appointments.
- Keep track of upcoming visits.
- Receive appointment reminders.

### ❤️ 5. Health Check-ins
- Record daily mood and symptom updates.
- Maintain basic health activity records.
- Support better communication between caregivers and family members.

### 📊 6. Health Insights
- View medication adherence information.
- Track missed and completed doses.
- Access medication-related insights and refill forecasts.

### 🔐 7. Privacy & Security
- Password hashing using bcrypt.
- JWT-based authentication.
- Role-based access control.
- Elder-controlled family permissions.
- Audit logging for important activities.

---

## 🛠️ Technology Stack

| Category | Technologies |
|---|---|
| Backend | Python, FastAPI |
| Frontend | HTML, CSS, JavaScript |
| Database | SQLite |
| Authentication | JWT, bcrypt |
| Notifications | Email notifications |
| Development | VS Code, Git, GitHub |

---

## 🏗️ Project Architecture

```text
              CARECIRCLE
                  |
       -----------------------
       |          |          |
     Elder     Caregiver   Family
       |          |          |
       -----------------------
                  |
           FastAPI Backend
                  |
       -----------------------
       |          |          |
 Authentication  Medication  Health
                 Management  Tracking
       |          |          |
       -----------------------
                  |
               SQLite
                  |
        Reminders & Notifications
```

---

## 📸 Application Screenshots

### 1. Login & Registration
<a href="https://github.com/arpita7819/CareCircle-AI-Hack-/blob/main/Screenshots/login.png">Login</a>

### 2. Main Dashboard
<a href="https://github.com/arpita7819/CareCircle-AI-Hack-/blob/main/Screenshots/Dashboard.png">Dashboard</a>

### 3. Medication Management
<a href="https://github.com/arpita7819/CareCircle-AI-Hack-/blob/main/Screenshots/Medications.png">Medication Management</a>

### 4. Appointment Management
![Appointment Management](screenshots/appointments.png)

### 5. Health Insights
![Health Insights](screenshots/insights.png)

### 6. Family Access & Permissions
![Family Access](screenshots/family-access.png)

---

## 📂 Project Structure

```text
CareCircle-AI-Hack-/
│
├── screenshots/
│   ├── login.png
│   ├── dashboard.png
│   ├── medication.png
│   ├── appointments.png
│   ├── insights.png
│   └── family-access.png
│
├── static/
│
├── app.py
├── test_e2e.py
├── requirements.txt
├── Dockerfile
├── .gitignore
└── README.md
```

---

## ⚙️ Installation & Setup

Follow these steps to run CareCircle locally.

### Prerequisites

- Python 3.10 or above
- pip
- Git

### Step 1: Clone the Repository

```bash
git clone https://github.com/arpita7819/CareCircle-AI-Hack-.git
```

### Step 2: Navigate to the Project Folder

```bash
cd CareCircle-AI-Hack-
```

### Step 3: Install Dependencies

```bash
python -m pip install -r requirements.txt
```

### Step 4: Start the Application

```bash
python -m uvicorn app:app --reload --port 8000
```

### Step 5: Open in Browser

Visit:

```text
http://127.0.0.1:8000
```

The CareCircle application should now be running locally.

---

## 🔮 Future Enhancements

- AI-powered personalized health insights.
- Voice-based medication assistance for elderly users.
- Multi-language support.
- Integration with wearable health devices.
- Advanced medication interaction checking.
- Mobile application support.
- Improved accessibility for elderly individuals.

---

## ⚠️ Disclaimer

CareCircle is a hackathon prototype intended for demonstration and educational purposes. Its medication information and interaction warnings are not a substitute for professional medical advice. Users should consult qualified healthcare professionals for medical decisions.

---

## 🎯 Our Vision

We envision a future where elderly individuals can live more independently while their families remain connected, informed, and involved.

**CareCircle – Because caring should always be connected. 💙**

---

## 👩‍💻 Developed By

**Arpita Kamboj**

GitHub: [@arpita7819](https://github.com/arpita7819)

Project Repository: [CareCircle – AI Hackathon](https://github.com/arpita7819/CareCircle-AI-Hack-)
