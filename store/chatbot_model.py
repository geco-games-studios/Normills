import random
import os
from typing import Tuple

import numpy as np
import torch
import torch.nn as nn
from transformers import AutoModel, AutoTokenizer

# Intent labels
INTENTS = {
    'product_inquiry': 0,
    'stock_check': 1,
    'shipping': 2,
    'recommendation': 3,
    'returns': 4,
    'general': 5,
}

INTENT_NAMES = {v: k for k, v in INTENTS.items()}

# Predefined responses
RESPONSES = {
    'product_inquiry': [
        "I'd be happy to help you find products. What type of items are you looking for?",
        "We have a great selection of products. Can you tell me more about what interests you?",
        "Let me help you discover products. What category interests you most?",
    ],
    'stock_check': [
        "I can check our inventory. Which product are you interested in?",
        "Let me look up that product for you.",
        "I'll help you find what we have in stock.",
    ],
    'shipping': [
        "We offer fast and reliable shipping. How can I help with your delivery?",
        "Shipping questions? I'm here to help!",
        "I can provide shipping information. What would you like to know?",
    ],
    'recommendation': [
        "I can recommend products based on your interests. Tell me what you're looking for!",
        "Let me suggest some great items for you.",
        "I have some recommendations. What are you interested in?",
    ],
    'returns': [
        "We have a simple returns and refunds process. How can I assist?",
        "I can help with returns. What's your concern?",
        "Let me explain our return policy.",
    ],
    'general': [
        "How can I assist you today?",
        "I'm here to help! What can I do for you?",
        "Feel free to ask me anything about our products and services.",
    ]
}


class IntentClassifier(nn.Module):
    """Simple intent classifier using transformer embeddings."""
    
    def __init__(self, hidden_size=256, num_intents=len(INTENTS)):
        super().__init__()
        self.fc1 = nn.Linear(384, hidden_size)
        self.dropout = nn.Dropout(0.3)
        self.fc2 = nn.Linear(hidden_size, num_intents)
        self.relu = nn.ReLU()
        
    def forward(self, embeddings):
        x = self.fc1(embeddings)
        x = self.relu(x)
        x = self.dropout(x)
        x = self.fc2(x)
        return x


class NoraChatbot:
    """Main chatbot class using PyTorch + Transformers."""
    
    def __init__(self, model_name='sentence-transformers/all-MiniLM-L6-v2', device=None):
        """Initialize the chatbot with a pre-trained model."""
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        
        # Load tokenizer and embedding model
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.embedding_model = AutoModel.from_pretrained(model_name).to(self.device)
        self.embedding_model.eval()
        
        # Load or initialize intent classifier
        self.intent_classifier = IntentClassifier().to(self.device)
        self.intent_classifier.eval()
        
        # Try to load saved weights
        self.model_path = os.path.join(os.path.dirname(__file__), 'chatbot_weights.pt')
        if os.path.exists(self.model_path):
            try:
                self.intent_classifier.load_state_dict(torch.load(self.model_path, map_location=self.device))
            except Exception as e:
                print(f"Could not load model weights: {e}")
    
    def get_embedding(self, text: str) -> np.ndarray:
        """Get sentence embedding using the pre-trained model."""
        with torch.no_grad():
            inputs = self.tokenizer(text, return_tensors='pt', truncation=True, max_length=512).to(self.device)
            outputs = self.embedding_model(**inputs)
            embeddings = outputs.last_hidden_state.mean(dim=1)
            return embeddings[0].cpu().numpy()
    
    def classify_intent(self, text: str) -> Tuple[str, float]:
        """Classify the intent of the user message."""
        try:
            embedding = self.get_embedding(text)
            embedding_tensor = torch.tensor(embedding, dtype=torch.float32).unsqueeze(0).to(self.device)
            
            with torch.no_grad():
                logits = self.intent_classifier(embedding_tensor)
                probs = torch.softmax(logits, dim=1)
                intent_id = torch.argmax(probs, dim=1).item()
                confidence = probs[0, intent_id].item()
            
            intent_name = INTENT_NAMES.get(intent_id, 'general')
            return intent_name, confidence
        except Exception as e:
            print(f"Error in intent classification: {e}")
            return 'general', 0.0
    
    def generate_response(self, text: str, product_name: str = '') -> str:
        """Generate a response based on user input and optional product context."""
        intent, confidence = self.classify_intent(text)
        
        # Choose a response for the detected intent.
        responses = RESPONSES.get(intent, RESPONSES['general'])
        response = random.choice(responses)

        if product_name:
            response = f"Regarding {product_name}, {response[0].lower() + response[1:] if response else response}"

        # Fallback if no text was generated for some reason.
        if not response:
            response = RESPONSES['general'][0]

        return response
    
    def save_weights(self):
        """Save model weights to disk."""
        try:
            torch.save(self.intent_classifier.state_dict(), self.model_path)
            print(f"Model saved to {self.model_path}")
        except Exception as e:
            print(f"Could not save model: {e}")


# Global chatbot instance
_chatbot_instance = None

def get_chatbot():
    """Get or create the global chatbot instance."""
    global _chatbot_instance
    if _chatbot_instance is None:
        _chatbot_instance = NoraChatbot()
    return _chatbot_instance
