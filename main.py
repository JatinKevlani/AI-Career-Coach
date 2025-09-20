import streamlit as st
import pandas as pd
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from typing import Optional
import os
import google.generativeai as genai
import time
import google.api_core.exceptions
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    st.error("GOOGLE_API_KEY not found. Please create a .env file with your Google API key.")
    st.stop()

os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY
genai.configure(api_key=GOOGLE_API_KEY)

class CareerPathOption(BaseModel):
    career_name: str
    career_description: str

class CareerPathOptions(BaseModel):
    options: list[CareerPathOption]

class SelectedCareerPath(BaseModel):
    career_name: Optional[str] = None

parser = PydanticOutputParser(pydantic_object=SelectedCareerPath)

st.title("Career Path Recommender")
st.header("Enter your personal information")
personal_info = st.text_area(
    "Personal info",
    placeholder="Describe your skills, interests, and goals...",
    height=200
)
st.header("Enter your previous projects experience")
previous_experience = st.text_area(
    "Previous experience",
    placeholder="Describe your previous projects and experiences...",
    height=200
)
st.header("Enter career path options")
career_path_options = st.text_area(
    "Career path options",
    placeholder="Describe your desired career paths (e.g., 1. Data Scientist\nDescription of Data Scientist\n2. Software Engineer\nDescription of Software Engineer...)",
    height=200
)

def parse_career_path(input_text):
    career_path = []
    lines = input_text.strip().split("\n")
    if len(lines) % 2 != 0:
        st.warning("Career path input should have alternating lines of career names and descriptions.")
        return CareerPathOptions(options=[])
    for i in range(0, len(lines), 2):
        name = lines[i].strip('1234567890. ').strip()
        description = lines[i+1].strip().strip('.').strip()
        if name and description:
            career_path.append(CareerPathOption(career_name=name, career_description=description))
    return CareerPathOptions(options=career_path)

def list_available_models():
    try:
        models = genai.list_models()
        return [model.name.split('/')[-1] for model in models if "generateContent" in model.supported_generation_methods]
    except Exception as e:
        st.error(f"Error listing models: {str(e)}")
        return []

def invoke_with_retry(chain, input_data, max_retries=3, initial_delay=2.0):
    retries = 0
    delay = initial_delay
    while retries < max_retries:
        try:
            return chain.invoke(input_data)
        except google.api_core.exceptions.ResourceExhausted as e:
            retries += 1
            if retries == max_retries:
                raise e
            st.warning(f"Quota exceeded, retrying in {delay} seconds... (Attempt {retries}/{max_retries})")
            time.sleep(delay)
            delay *= 2
    return None

if st.button("Get Recommendation"):
    if not personal_info.strip() or len(personal_info.strip()) < 10:
        st.error("Please provide detailed personal information (at least 10 characters).")
    elif not previous_experience.strip() or len(previous_experience.strip()) < 10:
        st.error("Please provide detailed previous experience (at least 10 characters).")
    elif not career_path_options.strip() or len(career_path_options.strip()) < 10:
        st.error("Please provide detailed career path options (at least 10 characters).")
    else:
        careers = parse_career_path(career_path_options)
        if not careers.options:
            st.error("No valid career paths provided.")
        else:
            prompt = ChatPromptTemplate.from_template('''
                I am a working professional looking to join a company and find the optimal career path for myself.
                You are a career advisor tasked with recommending the best career move.

                Personal information (skills, education, certifications, goals): {personal_info}
                Previous projects, experience, challenges, and aspirations: {previous_experience}
                Career paths of interest:
                {careers}

                I am looking for a career path that leverages my skills, aligns with my aspirations, and supports growth in the technology field. Based on my inputs, recommend the best career path.

                Respond only with the career name in the following JSON format:
                {format_instructions}
            ''')

            try:
                model = ChatGoogleGenerativeAI(temperature=1, model="gemini-1.5-flash")
            except Exception as e:
                st.error(f"Error initializing model: {str(e)}")
                available_models = list_available_models()
                if available_models:
                    st.info("Available models: " + ", ".join(available_models))
                    st.info("Please try updating the model name in the code (e.g., to 'gemini-2.5-pro') or check your API key and billing settings at https://ai.google.dev/gemini-api/docs/rate-limits.")
                st.stop()

            chain = prompt | model | parser

            careers_str = "\n".join([f"{i+1}. {opt.career_name}: {opt.career_description}" for i, opt in enumerate(careers.options)])
            INPUT = {
                "personal_info": personal_info.strip(),
                "previous_experience": previous_experience.strip(),
                "careers": careers_str,
                "format_instructions": parser.get_format_instructions()
            }

            print("Formatted Prompt:", prompt.format(**INPUT))

            try:
                result = invoke_with_retry(chain, INPUT, max_retries=3, initial_delay=2.0)
                results = [result] if result and result.career_name is not None else []
                if not results:
                    st.error("No valid recommendations received from the model.")
                else:
                    career_names = [career.career_name for career in results]
                    df = pd.DataFrame(career_names, columns=["Career Path"])
                    result_df = df['Career Path'].value_counts().reset_index()
                    result_df.columns = ['Career Path', 'Count']
                    result_df['Relative %'] = (result_df['Count'] / result_df['Count'].sum() * 100)

                    st.header("Career Path Recommendation")
                    st.dataframe(result_df)
            except google.api_core.exceptions.ResourceExhausted as e:
                st.error(f"Quota exceeded: {str(e)}")
                st.info("You have exceeded the free-tier quota for the Gemini API. Please enable billing or request a quota increase at https://console.cloud.google.com. Alternatively, try a different model like 'gemini-2.5-pro'.")
                available_models = list_available_models()
                if available_models:
                    st.info("Available models: " + ", ".join(available_models))
            except Exception as e:
                st.error(f"Error during model invocation: {str(e)}")
                available_models = list_available_models()
                if available_models:
                    st.info("Available models: " + ", ".join(available_models))
                    st.info("Try switching to 'gemini-2.5-pro' or 'gemini-2.5-flash'. If the issue persists, check your API key and billing settings at https://ai.google.dev/gemini-api/docs/rate-limits.")
