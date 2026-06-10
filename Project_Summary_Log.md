# DataVista (Job Marketing Analysis) — Project Summary Log

*This log documents the architecture, key features, and major changes implemented throughout the chat.*

## 1. Core Architecture 🏗️
- **Backend**: Python with **Flask**. Serves static files and provides a REST API.
- **Data Engine**: **Pandas** is used to load, clean, normalize, and cache CSV datasets into memory, allowing the API to respond in ~0ms.
- **Frontend**: Single Page Application (SPA) architecture written in **HTML/JS**. 
- **Styling**: Vanilla CSS, **Tailwind CSS**, and **Chart.js** for interactive data visualizations.

## 2. Static Dashboard & Features 📊
- **Data Normalization**: Cleaned the raw data from `ds_salaries.csv` (e.g., mapping "FT" to "Full-Time", converting ISO country codes to full country names, and creating a Remote Ratio scale).
- **Interactive Visualizations**: 
  - Top Roles by Volume
  - Experience vs. Salary
  - Remote vs. On-Site adoption
  - Top Hiring Locations
  - Salary Growth over Years
- **Global Filters**: Added dynamic dropdowns (Experience, Company Size) that instantly filter all charts simultaneously.
- **Underpaid Salary Calculator**: Built an interactive tool that compares a user's inputted salary against the real market average for their specific role, experience, and country.
- **Currency Localization**: A toggle button allows users to switch between global **USD** and localized **INR (₹)** across the entire application instantly.
- **AI Analyst Insights**: Added a custom UI element ("Data Analyst") beneath every chart. This simulated AI analyzes the chart's top data points and writes a human-readable insight (e.g., *"Senior Level commands the highest salary..."*).

## 3. Custom Dataset Upload 📁
- Added an `/api/upload_dataset` endpoint that accepts new CSV files dynamically.
- **Smart Mapping**: Built an intelligent mapping UI. If a user uploads a CSV where the columns don't match exactly (e.g., "Role" instead of "Job Title"), the UI auto-guesses the match and allows the user to correct it.
- **Error Handling**: Implemented strict backend checks. Datasets without mapped "Salary" or "Job Title" columns are rejected gracefully to prevent the dashboard from breaking.
- **AI Support Bot**: Built an interactive chatbot inside the upload modal that appears when an upload fails, answering user FAQs about CSV formatting and missing data requirements.
- **Revert Button**: Added a clickable "Custom Data" badge in the main header that allows users to instantly revert to the default dataset.

## 4. Live Market Data (`/live`) 🌐
- Built a secondary dashboard pulling real-time data from the **RemoteOK** and **Remotive** public APIs.
- **Graceful Fallbacks**: Since these public APIs frequently rate-limit requests, the backend implements a resilient caching system. If one API fails, it falls back to the other, or to a 1-hour cache.
- **Relative Timestamps**: Re-wrote python date parsing to calculate relative times (e.g., *"posted 3 hours ago"*) to show true real-time velocity.
- **Categorization**: Engineered a custom title-matching algorithm (`_detect_category`) that groups raw job titles into distinct sectors like "Data / ML / AI" or "Software Engineering".
- **Salary Transparency**: Extracted raw text salaries from live job descriptions, normalized them to integers, and added UI disclaimers explaining the reality of salary transparency in the live market.
