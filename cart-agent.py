import streamlit as st
import pandas as pd
import json
from typing import List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict
from langchain_openai import ChatOpenAI
import os

# Set up environment variables (replace with your actual key)
openai_api_key = st.secrets["OPENAI_API"]
os.environ["OPENAI_API_KEY"] = openai_api_key

# Ticket and User Management Classes
class Ticket:
    def __init__(self, ticket_id: str, user_email: str, issue: str, status: str = 'OPEN'):
        self.ticket_id = ticket_id
        self.user_email = user_email
        self.issue = issue
        self.status = status

    def to_dict(self):
        return {
            'ticket_id': self.ticket_id,
            'user_email': self.user_email,
            'issue': self.issue,
            'status': self.status
        }

class UserCart:
    def __init__(self, user_email: str, cart_id: str, cart_items: List[str]):
        self.user_email = user_email
        self.cart_id = cart_id
        self.cart_items = cart_items

    def to_dict(self):
        return {
            'user_email': self.user_email,
            'cart_id': self.cart_id,
            'cart_items': self.cart_items
        }

# Agent State
class AgentState(TypedDict):
    query: str
    tickets: List[Ticket]
    user_carts: List[UserCart]
    processed_tickets: List[Ticket]
    analysis_result: Dict[str, Any]

# Dummy Data
DUMMY_TICKETS = [
    {
        'ticket_id': 'TICKET-001',
        'user_email': 'john.doe@example.com',
        'issue': 'Unable to clear cart with multiple items',
        'status': 'OPEN'
    },
    {
        'ticket_id': 'TICKET-002',
        'user_email': 'jane.smith@example.com',
        'issue': 'Cart items not removing',
        'status': 'OPEN'
    },
    {
        'ticket_id': 'TICKET-003',
        'user_email': 'annie.smith@example.com',
        'issue': 'mail is not getting triggered for invoice',
        'status': 'OPEN'
    },
    {
        'ticket_id': 'TICKET-004',
        'user_email': 'lory.smith@example.com',
        'issue': 'pdp images is not loading',
        'status': 'OPEN'
    },
    {
        'ticket_id': 'TICKET-005',
        'user_email': 'mike.brown@example.com',
        'issue': 'Experiencing cart clearing issues',
        'status': 'OPEN'
    }
]

DUMMY_USER_CARTS = [
    {
        'user_email': 'john.doe@example.com',
        'cart_id': 'CART-001',
        'cart_items': ['Laptop', 'Mouse', 'Keyboard']
    },
    {
        'user_email': 'jane.smith@example.com',
        'cart_id': 'CART-002',
        'cart_items': ['Headphones', 'Charger', 'Phone Case']
    },
    {
        'user_email': 'mike.brown@example.com',
        'cart_id': 'CART-005',
        'cart_items': ['Book', 'Pen', 'Notebook']
    }
]

# LLM Analysis Function
def analyze_tickets_with_llm(tickets: List[Ticket], query: str) -> Dict[str, Any]:
    """Analyze tickets using LLM based on user query"""
    llm = ChatOpenAI(model="gpt-3.5-turbo")
    
    # Prepare ticket information for analysis
    ticket_info = "\n".join([
        f"Ticket ID: {ticket.ticket_id}, User: {ticket.user_email}, Issue: {ticket.issue}"
        for ticket in tickets
    ])
    
    # Craft a prompt that incorporates the user query
    prompt = f"""Analyze the following support tickets in the context of the user query: "{query}"
    
    Your tasks:
    1. Identify tickets directly related to the user query
    2. Extract user emails associated with matching tickets
    3. Provide a brief explanation of how the tickets match the query
    
    Ticket Details:
    {ticket_info}
    
    Provide your response in the following JSON format:
    {{
        "matching_tickets": [
            {{
                "ticket_id": "TICKET-XXX",
                "user_email": "user@example.com",
                "match_reason": "Explanation of how ticket matches query"
            }}
        ],
        "analysis_summary": "Brief summary of findings"
    }}
    """
    
    try:
        # Invoke LLM with the prompt
        response = llm.invoke(prompt)
        
        # Parse the JSON response
        analysis = json.loads(response.content)
        
        # Convert matching tickets to Ticket objects
        cart_related_tickets = [
            ticket for ticket in tickets 
            if ticket.ticket_id in [
                match_ticket['ticket_id'] 
                for match_ticket in analysis.get('matching_tickets', [])
            ]
        ]
        
        # Extract unique user emails
        affected_user_emails = list(set(
            ticket.user_email for ticket in cart_related_tickets
        ))
        
        return {
            "analysis": analysis.get('analysis_summary', 'No specific analysis'),
            "cart_related_tickets": cart_related_tickets,
            "affected_user_emails": affected_user_emails
        }
    
    except (json.JSONDecodeError, KeyError) as e:
        # Fallback analysis if JSON parsing fails
        # Use keyword matching based on user query
        keywords = query.lower().split()
        
        cart_related_tickets = [
            ticket for ticket in tickets 
            if any(keyword in ticket.issue.lower() for keyword in keywords)
        ]
        
        affected_user_emails = list(set(
            ticket.user_email for ticket in cart_related_tickets
        ))
        
        return {
            "analysis": f"Fallback analysis due to parsing error: {str(e)}",
            "cart_related_tickets": cart_related_tickets,
            "affected_user_emails": affected_user_emails
        }
    except Exception as e:
        # Handle any unexpected errors
        return {
            "analysis": f"Unexpected error: {str(e)}",
            "cart_related_tickets": [],
            "affected_user_emails": []
        }

# Utility Functions for Data Management
def load_tickets_from_dummy_data() -> List[Ticket]:
    """Load tickets from dummy data"""
    return [
        Ticket(
            ticket_id=ticket['ticket_id'],
            user_email=ticket['user_email'],
            issue=ticket['issue'],
            status=ticket['status']
        ) for ticket in DUMMY_TICKETS
    ]

def load_user_carts_from_dummy_data() -> List[UserCart]:
    """Load user carts from dummy data"""
    return [
        UserCart(
            user_email=cart['user_email'],
            cart_id=cart['cart_id'],
            cart_items=cart['cart_items']
        ) for cart in DUMMY_USER_CARTS
    ]

def save_dummy_tickets(tickets: List[Ticket]):
    """Update dummy tickets data globally"""
    global DUMMY_TICKETS
    DUMMY_TICKETS = [
        {
            'ticket_id': ticket.ticket_id,
            'user_email': ticket.user_email,
            'issue': ticket.issue,
            'status': ticket.status
        } for ticket in tickets
    ]

def save_dummy_user_carts(user_carts: List[UserCart]):
    """Update dummy user carts data"""
    global DUMMY_USER_CARTS
    DUMMY_USER_CARTS = [cart.to_dict() for cart in user_carts]

def clear_user_cart(user_email: str, user_carts: List[UserCart]) -> Dict[str, Any]:
    """Clear cart for a specific user"""
    # Find user's cart
    user_cart = next((cart for cart in user_carts if cart.user_email == user_email), None)
    
    if user_cart:
        # Simulate cart clearing
        user_cart.cart_items = []
        return {
            "status": "SUCCESS",
            "message": f"Cart cleared for {user_email}",
            "cart_id": user_cart.cart_id
        }
    
    return {
        "status": "FAILED",
        "message": f"No cart found for {user_email}"
    }

# Workflow Nodes
def process_query(state: AgentState) -> Dict:
    """Process user query and analyze tickets"""
    tickets = load_tickets_from_dummy_data()
    
    # Analyze tickets using the function directly
    analysis_result = analyze_tickets_with_llm(tickets, state['query'])
    
    return {
        "tickets": tickets,
        "analysis_result": analysis_result
    }

def process_cart_clearing(state: AgentState) -> Dict:
    """Process cart clearing for identified users"""
    user_carts = load_user_carts_from_dummy_data()
    analysis_result = state['analysis_result']
    
    processed_tickets = []
    for user_email in analysis_result['affected_user_emails']:
        cart_clear_result = clear_user_cart(user_email, user_carts)
        
        # Find and update corresponding tickets
        matching_tickets = [
            ticket for ticket in state['tickets'] 
            if ticket.user_email == user_email
        ]
        
        for ticket in matching_tickets:
            ticket.status = "RESOLVED" if cart_clear_result['status'] == "SUCCESS" else "PENDING"
            processed_tickets.append(ticket)
    
    # Save updated dummy data
    save_dummy_tickets(processed_tickets)
    save_dummy_user_carts(user_carts)
    
    return {
        "processed_tickets": processed_tickets,
        "user_carts": user_carts
    }

# LangGraph Workflow
def create_cart_clearing_workflow():
    graph = StateGraph(AgentState)
    
    graph.add_node("process_query", process_query)
    graph.add_node("process_cart_clearing", process_cart_clearing)
    
    graph.set_entry_point("process_query")
    graph.add_edge("process_query", "process_cart_clearing")
    graph.add_edge("process_cart_clearing", END)
    
    return graph.compile()

# Streamlit Interface
def main():
    st.title("Support Solver")
    
    # User query input
    user_query = st.text_input("Describe the ticket or issue you're experiencing:")
    
    # Create a mutable copy of tickets
    current_tickets = DUMMY_TICKETS.copy()
    
    # Display Initial Ticket Data in Sidebar
    st.sidebar.write("### Ticket Data")
    for ticket in current_tickets:
        st.sidebar.write(f"Ticket ID: {ticket['ticket_id']}")
        st.sidebar.write(f"User Email: {ticket['user_email']}")
        st.sidebar.write(f"Issue: {ticket['issue']}")
        st.sidebar.write(f"Status: {ticket['status']}")
        st.sidebar.write("---")
    
    if st.button("Analyze and Resolve"):
        # Initialize workflow
        workflow = create_cart_clearing_workflow()
        
        # Initial state with user query
        initial_state = {
            "query": user_query,
            "tickets": [],
            "user_carts": [],
            "processed_tickets": [],
            "analysis_result": {}
        }
        
        # Run workflow
        result = workflow.invoke(initial_state)
        
        # Update current tickets
        for processed_ticket in result['processed_tickets']:
            for ticket in current_tickets:
                if ticket['ticket_id'] == processed_ticket.ticket_id:
                    ticket['status'] = processed_ticket.status
        
        # Display Ticket Analysis
        st.write("### Ticket Analysis")
        st.write(result['analysis_result']['analysis'])
        
        # Display Processed Tickets
        st.write("### Processed Tickets")
        for ticket in result['processed_tickets']:
            st.write(f"Ticket ID: {ticket.ticket_id}")
            st.write(f"User Email: {ticket.user_email}")
            st.write(f"Status: {ticket.status}")
            st.write("---")
        
        # Update Sidebar with New Statuses
        st.sidebar.write("### Updated Ticket Data")
        for ticket in current_tickets:
            st.sidebar.write(f"Ticket ID: {ticket['ticket_id']}")
            st.sidebar.write(f"User Email: {ticket['user_email']}")
            st.sidebar.write(f"Issue: {ticket['issue']}")
            st.sidebar.write(f"Status: {ticket['status']}")
            st.sidebar.write("---")

if __name__ == "__main__":
    main()
