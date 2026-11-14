import streamlit as st
from ai.predict import predict_fraud

st.set_page_config(page_title="JobProof", page_icon="🔍")
st.title("JobProof")
st.caption("Check a job posting for signs of fraud.")

st.write(
    "Paste as much of the posting as you can. The model was trained on the "
    "title, company profile, description, requirements and benefits together, "
    "so filling in more boxes gives a more reliable result."
)

title = st.text_input("Job title")
company_profile = st.text_area("Company profile (optional)", height=100)
description = st.text_area("Job description", height=200)
requirements = st.text_area("Requirements (optional)", height=100)
benefits = st.text_area("Benefits (optional)", height=100)

if st.button("Analyze", type="primary"):
    if not description.strip():
        st.warning("Please paste a job description first.")
    else:
        result = predict_fraud(
            description,
            title=title,
            company_profile=company_profile,
            requirements=requirements,
            benefits=benefits,
        )

        st.subheader("Result")
        if result["prediction"] == 1:
            st.error(result["classification"])
        else:
            st.success(result["classification"])

        st.metric("ML risk score (0-100)", result["ml_score"])
        st.progress(result["ml_score"] / 100)

        filled = sum(bool(t.strip()) for t in (title, company_profile, requirements, benefits))
        if filled == 0:
            st.info("Only the description was provided. Accuracy is lower with partial input.")

        # Cybersecurity checks (suspicious emails, URLs, domains) will be added here
        # once the security/ module is implemented.
        st.caption("ML text analysis only. Cybersecurity checks are not connected yet. "
                   "This is an indicator, not proof.")
