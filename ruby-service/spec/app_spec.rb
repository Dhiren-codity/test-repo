# frozen_string_literal: true

require 'spec_helper'
require 'rack/test'
require 'json'
require 'time'
require_relative '../app/app'

RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /analyze' do
    it 'accepts valid content' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 85.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('summary')
    end
  end

  describe 'GET /status' do
    it 'reports healthy for all services when upstream health endpoints return 200' do
      allow(HTTParty).to receive(:get) do |_url, _opts|
        instance_double('Response', code: 200)
      end

      get '/status'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json.dig('services', 'ruby', 'status')).to eq('healthy')
      expect(json.dig('services', 'go', 'status')).to eq('healthy')
      expect(json.dig('services', 'python', 'status')).to eq('healthy')
    end

    it 'handles unreachable and unhealthy upstream services' do
      allow(HTTParty).to receive(:get) do |url, _opts|
        raise StandardError, 'connection refused' if url.include?('8080')

        instance_double('Response', code: 500)
      end

      get '/status'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json.dig('services', 'go', 'status')).to eq('unreachable')
      expect(json.dig('services', 'go')).to have_key('error')
      expect(json.dig('services', 'python', 'status')).to eq('unhealthy')
    end
  end

  describe 'POST /analyze additional cases' do
    it 'returns 400 when content is missing' do
      post '/analyze', { path: 'file.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing content')
    end

    it 'falls back to params when JSON body is invalid' do
      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/parse', hash_including(content: 'puts 1', path: 'test.rb'))
        .and_return({ 'language' => 'ruby', 'lines' => ['puts 1'] })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'puts 1', language: 'ruby'))
        .and_return({ 'score' => 92.0, 'issues' => [] })

      post '/analyze?content=puts+1&path=test.rb', 'INVALID_JSON', 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json.dig('summary', 'language')).to eq('ruby')
    end

    it 'detects unknown language when no path is provided' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/parse', hash_including(content: 'code', path: 'unknown'))
        .and_return({ 'language' => 'unknown', 'lines' => [] })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'code', language: 'unknown'))
        .and_return({ 'score' => 70.0, 'issues' => [] })

      post '/analyze', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json.dig('summary', 'language')).to eq('unknown')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when required params are missing' do
      post '/diff', { old_content: 'old' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing old_content or new_content')
    end

    it 'returns diff result and new review' do
      diff_result = { 'changes' => [{ 'type' => 'add', 'line' => 1 }] }
      review_result = { 'score' => 95.0, 'issues' => [] }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(old_content: 'old', new_content: 'new'))
        .and_return(diff_result)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'new'))
        .and_return(review_result)

      post '/diff', { old_content: 'old', new_content: 'new' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['diff']).to eq(diff_result)
      expect(json['new_code_review']).to eq(review_result)
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing content')
    end

    it 'computes overall_quality with penalties and clamps to 0' do
      metrics = { 'complexity' => 3 }
      review = { 'score' => 80, 'issues' => %w[a b] }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'x'))
        .and_return(metrics)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'x'))
        .and_return(review)

      post '/metrics', { content: 'x' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['metrics']).to eq(metrics)
      expect(json['review']).to eq(review)
      expect(json['overall_quality']).to eq(0.0)
    end

    it 'computes a positive overall_quality' do
      metrics = { 'complexity' => 1 }
      review = { 'score' => 90, 'issues' => [] }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'ok'))
        .and_return(metrics)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'ok'))
        .and_return(review)

      post '/metrics', { content: 'ok' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['overall_quality']).to eq(80.0)
    end

    it 'returns 0.0 overall_quality when a downstream service errors' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'oops'))
        .and_return({ 'error' => 'timeout' })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'oops'))
        .and_return({ 'score' => 90, 'issues' => [] })

      post '/metrics', { content: 'oops' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['overall_quality']).to eq(0.0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing files array')
    end

    it 'returns aggregated statistics and a computed health score' do
      files = [{ 'path' => 'a.rb', 'content' => 'puts 1' }, { 'path' => 'b.py', 'content' => 'pass' }]
      file_stats = { 'total_files' => 2, 'total_lines' => 10, 'languages' => { 'ruby' => 1, 'python' => 1 } }
      review_stats = { 'average_score' => 80.0, 'total_issues' => 2, 'average_complexity' => 0.1 }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(files: files))
        .and_return(file_stats)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(files: files))
        .and_return(review_stats)

      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect { Time.iso8601(json['timestamp']) }.not_to raise_error
      expect(json.dig('summary', 'total_files')).to eq(2)
      expect(json.dig('summary', 'average_quality_score')).to eq(80.0)
      expect(json.dig('summary', 'health_score')).to eq(75.0)
    end

    it 'returns health_score 0.0 when downstream services error' do
      files = [{ 'path' => 'c.js', 'content' => 'console.log(1)' }]
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(files: files))
        .and_return({ 'error' => 'failed' })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(files: files))
        .and_return({ 'average_score' => 50.0, 'total_issues' => 5, 'average_complexity' => 0.2 })

      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json.dig('summary', 'health_score')).to eq(0.0)
    end
  end
end
